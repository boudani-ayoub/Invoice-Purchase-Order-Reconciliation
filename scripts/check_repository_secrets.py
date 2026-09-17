"""Fail CI on narrow, high-confidence committed-secret regressions."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
PRIVATE_KEY = re.compile(rb"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")
DATABASE_CREDENTIAL = re.compile(
    rb"postgres(?:ql)?(?:\+psycopg)?://[^\s:/@]+:([^\s/@]+)@", re.IGNORECASE
)
SECRET_ASSIGNMENT = re.compile(
    rb"^(AUTH_CSRF_SECRET|SMTP_PASSWORD)[ \t]*=[ \t]*([^\s#]+)", re.MULTILINE
)
TOKEN_PREFIX = re.compile(rb"(?:github_pat_|gh[oprsu]_|AKIA)[A-Za-z0-9_-]{12,}")
PLACEHOLDERS = (b"${", b"{{", b"<", b"replace", b"example")
ALLOWED_LOCAL_DATABASE_PASSWORDS = {b"postgres"}


def tracked_paths() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in completed.stdout.split(b"\0") if item]


def path_violations(path: Path) -> list[str]:
    relative = path.relative_to(ROOT)
    name = relative.name.lower()
    violations = []
    if name.startswith(".env") and not name.endswith(".example"):
        violations.append("tracked environment file")
    if path.suffix.lower() in {".key", ".pem", ".p12", ".pfx"}:
        violations.append("tracked credential or private-key container")
    return violations


def content_violations(data: bytes) -> list[str]:
    violations = []
    if PRIVATE_KEY.search(data):
        violations.append("private-key material")
    for match in DATABASE_CREDENTIAL.finditer(data):
        password = match.group(1).lower()
        prefix = data[max(0, match.start() - 80) : match.end() + 80].lower()
        allowed_ci_fixture = (
            password in ALLOWED_LOCAL_DATABASE_PASSWORDS and b"@127.0.0.1" in prefix
        )
        documented_placeholder = any(marker in password for marker in PLACEHOLDERS)
        test_fixture = b"postgresql://u:secret@localhost/" in prefix
        if not (allowed_ci_fixture or documented_placeholder or test_fixture):
            violations.append("database URL contains an inline password")
            break
    for match in SECRET_ASSIGNMENT.finditer(data):
        value = match.group(2).lower()
        if value and not any(marker in value for marker in PLACEHOLDERS):
            violations.append("private setting contains a committed value")
            break
    if TOKEN_PREFIX.search(data):
        violations.append("credential-like token prefix")
    return violations


def scan(paths: list[Path]) -> list[tuple[Path, str]]:
    findings = []
    for path in paths:
        for reason in path_violations(path):
            findings.append((path, reason))
        try:
            data = path.read_bytes()
        except OSError:
            findings.append((path, "tracked file could not be inspected"))
            continue
        for reason in content_violations(data):
            findings.append((path, reason))
    return findings


def main() -> None:
    findings = scan(tracked_paths())
    if findings:
        for path, reason in findings:
            print(f"{path.relative_to(ROOT)}: {reason}")
        raise SystemExit(
            "Potential committed secret detected; values are intentionally suppressed."
        )
    print("Tracked-file secret regression checks passed.")


if __name__ == "__main__":
    main()
