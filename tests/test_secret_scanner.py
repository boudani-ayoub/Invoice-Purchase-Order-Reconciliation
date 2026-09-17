from scripts.check_repository_secrets import content_violations, path_violations


def test_secret_scanner_rejects_high_confidence_material_without_echoing_values(tmp_path):
    data = b"\n".join(
        (
            b"-----BEGIN " + b"PRIVATE KEY-----",
            b"DATABASE_URL=postgresql://" + b"service:actual-password@db.internal/product",
            b"SMTP_PASSWORD=" + b"actual-password",
            b"github_" + b"pat_abcdefghijklmnopqrstuvwxyz",
        )
    )
    findings = content_violations(data)
    assert findings == [
        "private-key material",
        "database URL contains an inline password",
        "private setting contains a committed value",
        "credential-like token prefix",
    ]
    assert "actual-password" not in " ".join(findings)


def test_secret_scanner_accepts_empty_placeholders_and_disposable_ci_database():
    assert not content_violations(
        b"AUTH_CSRF_SECRET=\n"
        b"SMTP_PASSWORD=${SMTP_PASSWORD}\n"
        b"TEST_DATABASE_ADMIN_URL=postgresql+psycopg://postgres:postgres@127.0.0.1/postgres\n"
    )


def test_secret_scanner_rejects_tracked_secret_file_shapes(monkeypatch, tmp_path):
    from scripts import check_repository_secrets as scanner

    monkeypatch.setattr(scanner, "ROOT", tmp_path)
    assert path_violations(tmp_path / ".env.production") == ["tracked environment file"]
    assert path_violations(tmp_path / "server.key") == [
        "tracked credential or private-key container"
    ]
    assert path_violations(tmp_path / ".env.example") == []
