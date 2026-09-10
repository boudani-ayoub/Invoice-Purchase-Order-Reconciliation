"""Organization-scoped run transactions; no reconstruction of historical reports."""

import base64
import binascii
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, tuple_

from reconcile.analysis.models import REQUIRED_SOURCES, AnalysisMode
from reconcile.auth.policy import Permission
from reconcile.auth.service_errors import AuthError
from reconcile.auth.sessions import Sessions
from reconcile.persistence import audit
from reconcile.persistence.audit import AuditEventType
from reconcile.persistence.findings import persist_findings
from reconcile.persistence.imports import SourceEvidence, import_sources
from reconcile.persistence.models import (
    AnalysisRun,
    AnalysisSource,
    ResultSnapshot,
    RunStatus,
    SourceFile,
)
from reconcile.persistence.run_policy import HISTORY_PAGE_MAX, SNAPSHOT_SCHEMA_VERSION


def run_metadata(run: AnalysisRun, summary: dict) -> dict[str, object]:
    return {
        "id": str(run.id),
        "mode": run.analysis_mode,
        "status": run.status,
        "title": run.title,
        "note": run.note,
        "created_at": run.created_at.astimezone(UTC).isoformat(),
        "updated_at": run.updated_at.astimezone(UTC).isoformat(),
        "archived_at": run.archived_at.astimezone(UTC).isoformat() if run.archived_at else None,
        "version": run.version,
        "created_by_user_id": str(run.created_by_user_id) if run.created_by_user_id else None,
        "summary": summary,
    }


def encode_cursor(run: AnalysisRun) -> str:
    raw = json.dumps([run.created_at.isoformat(), str(run.id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, UUID]:
    try:
        if not 1 <= len(value) <= 256:
            raise ValueError
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        parsed = json.loads(raw)
        if (
            not isinstance(parsed, list)
            or len(parsed) != 2
            or not all(isinstance(v, str) for v in parsed)
        ):
            raise ValueError
        timestamp = datetime.fromisoformat(parsed[0])
        if timestamp.tzinfo is None:
            raise ValueError
        return timestamp.astimezone(UTC), UUID(parsed[1])
    except (ValueError, TypeError, OverflowError, binascii.Error):
        raise AuthError(400, "invalid_cursor", "The history cursor is invalid.") from None


class Runs:
    def __init__(self, sessions: Sessions, engine_version: str) -> None:
        self.sessions, self.engine_version = sessions, engine_version

    def create(
        self,
        raw: str,
        organization: UUID,
        mode: AnalysisMode,
        sources: tuple[SourceEvidence, ...],
        report: dict,
        request_id: UUID,
    ) -> dict:
        if (
            {source.source_type for source in sources} != set(REQUIRED_SOURCES[mode])
            or len(sources) != len(REQUIRED_SOURCES[mode])
            or report["mode"] != mode
        ):
            raise ValueError("Analysis source contract mismatch")
        with self.sessions.authorized_transaction(raw, Permission.RUN_ANALYSIS) as (
            principal,
            session,
        ):
            if principal.active_organization_id != organization:
                raise AuthError(403, "forbidden", "The active organization changed. Run again.")
            evidence = import_sources(session, organization, sources)
            now = self.sessions.clock()
            run = AnalysisRun(
                organization_id=organization,
                created_by_user_id=principal.user_id,
                analysis_mode=mode,
                status=RunStatus.COMPLETED,
                started_at=now,
                completed_at=now,
                created_at=now,
                updated_at=now,
            )
            session.add(run)
            session.flush()
            session.add_all(
                AnalysisSource(
                    organization_id=organization, analysis_run_id=run.id, source_file_id=source.id
                )
                for source in evidence.sources
            )
            persist_findings(session, organization, run.id, report, evidence)
            session.add(
                ResultSnapshot(
                    organization_id=organization,
                    analysis_run_id=run.id,
                    schema_version=SNAPSHOT_SCHEMA_VERSION,
                    engine_version=self.engine_version,
                    report=report,
                )
            )
            audit.record_event(
                session,
                organization_id=organization,
                actor=principal.user_id,
                run_id=run.id,
                request_id=request_id,
                event_type=AuditEventType.ANALYSIS_COMPLETED,
                details={"mode": mode, "version": run.version},
            )
            return {"run": run_metadata(run, report["summary"]), "report": report}

    def list(
        self, raw: str, *, mode: AnalysisMode | None, archived: bool, limit: int, cursor: str | None
    ) -> dict:
        if not 1 <= limit <= HISTORY_PAGE_MAX:
            raise AuthError(422, "invalid_limit", "History page size is out of range.")
        after = decode_cursor(cursor) if cursor else None
        with self.sessions.authorized_transaction(raw, Permission.VIEW_RUN_HISTORY) as (
            principal,
            session,
        ):
            query = (
                select(AnalysisRun, ResultSnapshot.report["summary"])
                .join(
                    ResultSnapshot,
                    (ResultSnapshot.analysis_run_id == AnalysisRun.id)
                    & (ResultSnapshot.organization_id == AnalysisRun.organization_id),
                )
                .where(
                    AnalysisRun.organization_id == principal.active_organization_id,
                    AnalysisRun.archived_at.is_not(None)
                    if archived
                    else AnalysisRun.archived_at.is_(None),
                )
            )
            if mode:
                query = query.where(AnalysisRun.analysis_mode == mode)
            if after:
                query = query.where(tuple_(AnalysisRun.created_at, AnalysisRun.id) < after)
            rows = session.execute(
                query.order_by(AnalysisRun.created_at.desc(), AnalysisRun.id.desc()).limit(
                    limit + 1
                )
            ).all()
            items = []
            for run, summary in rows[:limit]:
                metadata = run_metadata(run, summary)
                metadata.pop("note")
                items.append(metadata)
            return {
                "items": items,
                "next_cursor": encode_cursor(rows[limit - 1][0]) if len(rows) > limit else None,
            }

    @staticmethod
    def _stored(session, organization: UUID, run_id: UUID):
        found = session.execute(
            select(AnalysisRun, ResultSnapshot)
            .join(
                ResultSnapshot,
                (ResultSnapshot.analysis_run_id == AnalysisRun.id)
                & (ResultSnapshot.organization_id == AnalysisRun.organization_id),
            )
            .where(AnalysisRun.organization_id == organization, AnalysisRun.id == run_id)
        ).first()
        if found is None:
            raise AuthError(404, "not_found", "Run not found.")
        return found

    def detail(self, raw: str, run_id: UUID) -> dict:
        with self.sessions.authorized_transaction(raw, Permission.VIEW_RUN_HISTORY) as (
            principal,
            session,
        ):
            run, snapshot = self._stored(session, principal.active_organization_id, run_id)
            sources = session.scalars(
                select(SourceFile)
                .join(
                    AnalysisSource,
                    (AnalysisSource.source_file_id == SourceFile.id)
                    & (AnalysisSource.organization_id == SourceFile.organization_id),
                )
                .where(
                    AnalysisSource.organization_id == principal.active_organization_id,
                    AnalysisSource.analysis_run_id == run.id,
                )
                .order_by(SourceFile.source_type)
            ).all()
            return {
                "run": run_metadata(run, snapshot.report["summary"]),
                "report": snapshot.report,
                "schema_version": snapshot.schema_version,
                "engine_version": snapshot.engine_version,
                "sources": [
                    {
                        "source_type": s.source_type,
                        "filename": s.original_filename,
                        "size_bytes": s.size_bytes,
                        "sha256": s.sha256,
                        "created_at": s.created_at.astimezone(UTC).isoformat(),
                    }
                    for s in sources
                ],
            }

    def mutate(
        self,
        raw: str,
        run_id: UUID,
        expected_version: int,
        changes: dict,
        request_id: UUID,
        *,
        archive: bool | None = None,
    ) -> dict:
        permission = (
            Permission.ARCHIVE_RUN if archive is not None else Permission.UPDATE_RUN_METADATA
        )
        if set(changes) - {"title", "note"}:
            raise ValueError("Unsupported metadata fields")
        with self.sessions.authorized_transaction(raw, permission) as (principal, session):
            organization = principal.active_organization_id
            # Lock the current row before comparing versions; stale writers cannot both succeed.
            run = session.scalar(
                select(AnalysisRun)
                .where(AnalysisRun.organization_id == organization, AnalysisRun.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise AuthError(404, "not_found", "Run not found.")
            if run.version != expected_version:
                raise AuthError(
                    409,
                    "version_conflict",
                    "This run was updated by someone else. Refresh to see the latest version.",
                )
            _, snapshot = self._stored(session, organization, run.id)
            if archive is None:
                fields = sorted(changes)
                for name, value in changes.items():
                    setattr(run, name, value)
                event = AuditEventType.RUN_METADATA_UPDATED
            else:
                run.archived_at = max(self.sessions.clock(), run.created_at) if archive else None
                fields = ["archived_at"]
                event = AuditEventType.RUN_ARCHIVED if archive else AuditEventType.RUN_RESTORED
            run.version += 1
            session.flush()
            session.refresh(run)
            audit.record_event(
                session,
                organization_id=organization,
                actor=principal.user_id,
                run_id=run.id,
                request_id=request_id,
                event_type=event,
                details={
                    "changed_fields": fields,
                    "previous_version": expected_version,
                    "new_version": run.version,
                },
            )
            return run_metadata(run, snapshot.report["summary"])
