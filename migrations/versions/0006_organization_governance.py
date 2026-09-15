"""Add organization administration, invitations, and retained governance events."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_IDENTITY_TABLES = ("organization_invitations", "governance_events")


def _record_columns():
    return (
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def _membership_role():
    return sa.Enum(
        "MEMBER",
        "AP_MANAGER",
        "ORG_ADMIN",
        name="membershiprole",
        native_enum=False,
        create_constraint=True,
    )


def upgrade() -> None:
    for table in ("organizations", "organization_memberships"):
        op.add_column(table, sa.Column("version", sa.Integer(), server_default="1", nullable=False))
        op.create_check_constraint(op.f(f"ck_{table}_version_positive"), table, "version > 0")
    op.create_index(
        "ix_organization_memberships_history",
        "organization_memberships",
        ["organization_id", "created_at", "id"],
    )

    op.create_table(
        "organization_invitations",
        *_record_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_email", sa.Text(), nullable=False),
        sa.Column("role", _membership_role(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "ACCEPTED",
                "REVOKED",
                name="invitationstatus",
                native_enum=False,
                create_constraint=True,
            ),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organization_invitations")),
        sa.UniqueConstraint(
            "organization_id",
            "id",
            name=op.f("uq_organization_invitations_organization_id_id"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
            name=op.f("fk_organization_invitations_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "created_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name=op.f("fk_organization_invitations_organization_id_organization_memberships"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "accepted_by_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name="fk_organization_invitations_acceptor_membership",
        ),
        sa.CheckConstraint(
            "normalized_email = lower(btrim(normalized_email)) "
            "AND normalized_email ~ '^[^@[:space:]]+@[^@[:space:]]+$' "
            "AND length(normalized_email) <= 254",
            name=op.f("ck_organization_invitations_email_normalized"),
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_organization_invitations_token_hash_shape"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_organization_invitations_lifetime")
        ),
        sa.CheckConstraint(
            "version > 0", name=op.f("ck_organization_invitations_version_positive")
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND accepted_at IS NULL "
            "AND accepted_by_user_id IS NULL AND revoked_at IS NULL) OR "
            "(status = 'ACCEPTED' AND accepted_at IS NOT NULL "
            "AND accepted_by_user_id IS NOT NULL AND revoked_at IS NULL) OR "
            "(status = 'REVOKED' AND accepted_at IS NULL "
            "AND accepted_by_user_id IS NULL AND revoked_at IS NOT NULL)",
            name=op.f("ck_organization_invitations_lifecycle"),
        ),
    )
    op.create_index(
        "ix_organization_invitations_token",
        "organization_invitations",
        ["token_hash"],
        unique=True,
    )
    op.create_index(
        "uq_organization_invitations_pending_email",
        "organization_invitations",
        ["organization_id", "normalized_email"],
        unique=True,
        postgresql_where=sa.text("status = 'PENDING'"),
    )
    op.create_index(
        "ix_organization_invitations_history",
        "organization_invitations",
        ["organization_id", "created_at", "id"],
    )

    op.create_table(
        "governance_events",
        *_record_columns(),
        sa.Column("organization_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "ORGANIZATION_RENAMED",
                "INVITATION_CREATED",
                "INVITATION_REVOKED",
                "INVITATION_ACCEPTED",
                "MEMBER_ROLE_CHANGED",
                "MEMBER_DEACTIVATED",
                "MEMBER_REACTIVATED",
                name="governanceeventtype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "resource_type",
            sa.Enum(
                "ORGANIZATION",
                "MEMBERSHIP",
                "INVITATION",
                name="governanceresourcetype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_governance_events")),
        sa.UniqueConstraint(
            "organization_id", "id", name=op.f("uq_governance_events_organization_id_id")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="RESTRICT",
            name=op.f("fk_governance_events_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id", "actor_user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name=op.f("fk_governance_events_organization_id_organization_memberships"),
        ),
        sa.CheckConstraint(
            "jsonb_typeof(metadata) = 'object' AND octet_length(metadata::text) <= 2048",
            name=op.f("ck_governance_events_metadata_bound"),
        ),
    )
    op.create_index(
        "ix_governance_events_chronology",
        "governance_events",
        ["organization_id", "created_at", "id"],
    )

    for table in _IDENTITY_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'CREATE POLICY identity_access ON "{table}" TO reconcile_identity '
            "USING (true) WITH CHECK (true)"
        )
    op.execute("GRANT SELECT, INSERT ON organization_invitations TO reconcile_identity")
    op.execute(
        "GRANT UPDATE (status, accepted_at, accepted_by_user_id, revoked_at, version) "
        "ON organization_invitations TO reconcile_identity"
    )
    op.execute("GRANT SELECT, INSERT ON governance_events TO reconcile_identity")
    op.execute("GRANT UPDATE (name, version) ON organizations TO reconcile_identity")
    op.execute(
        "GRANT UPDATE (role, status, version) ON organization_memberships TO reconcile_identity"
    )
    op.execute(
        "CREATE TRIGGER touch_updated_at BEFORE UPDATE ON organization_invitations "
        "FOR EACH ROW EXECUTE FUNCTION touch_updated_at()"
    )
    op.execute("""
        CREATE FUNCTION protect_governance_event() RETURNS trigger LANGUAGE plpgsql
        SET search_path = pg_catalog, public, pg_temp AS $body$
        BEGIN RAISE EXCEPTION 'Governance events are immutable'; END $body$;
    """)
    op.execute(
        "CREATE TRIGGER protect_governance_event BEFORE UPDATE OR DELETE ON governance_events "
        "FOR EACH ROW EXECUTE FUNCTION protect_governance_event()"
    )


def downgrade() -> None:
    connection = op.get_bind()
    retained = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM organization_invitations) "
            "OR EXISTS (SELECT 1 FROM governance_events) "
            "OR EXISTS (SELECT 1 FROM organizations WHERE version <> 1) "
            "OR EXISTS (SELECT 1 FROM organization_memberships WHERE version <> 1)"
        )
    )
    if retained:
        raise RuntimeError("Phase 6 governance history cannot be downgraded safely")
    op.execute(
        "REVOKE UPDATE (role, status, version) ON organization_memberships FROM reconcile_identity"
    )
    op.execute("REVOKE UPDATE (name, version) ON organizations FROM reconcile_identity")
    op.drop_table("governance_events")
    op.execute("DROP FUNCTION protect_governance_event()")
    op.drop_table("organization_invitations")
    op.drop_index("ix_organization_memberships_history", table_name="organization_memberships")
    for table in ("organization_memberships", "organizations"):
        op.drop_constraint(op.f(f"ck_{table}_version_positive"), table, type_="check")
        op.drop_column(table, "version")
