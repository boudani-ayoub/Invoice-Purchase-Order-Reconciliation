"""Add identity credentials, sessions, single-use mail tokens, and throttles."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

_AUTH_TABLES = ("user_credentials", "auth_sessions", "email_tokens", "auth_throttles")


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


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "user_credentials",
        *_record_columns(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("password_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_user_credentials"),
        sa.UniqueConstraint("user_id", name="uq_user_credentials_user_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_user_credentials_user_id_users"
        ),
        sa.CheckConstraint(
            "password_hash LIKE '$argon2id$%'", name=op.f("ck_user_credentials_argon2id_hash")
        ),
    )
    op.create_table(
        "auth_sessions",
        *_record_columns(),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("active_organization_id", sa.Uuid(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_auth_sessions_user_id_users"
        ),
        sa.ForeignKeyConstraint(
            ["active_organization_id", "user_id"],
            ["organization_memberships.organization_id", "organization_memberships.user_id"],
            ondelete="RESTRICT",
            name=op.f("fk_auth_sessions_active_organization_id_organization_memberships"),
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_sessions_token_hash_shape")
        ),
        sa.CheckConstraint(
            "idle_expires_at <= absolute_expires_at AND created_at < absolute_expires_at",
            name=op.f("ck_auth_sessions_session_lifetimes"),
        ),
    )
    op.create_index("ix_auth_sessions_user_revoked", "auth_sessions", ["user_id", "revoked_at"])
    op.create_table(
        "email_tokens",
        *_record_columns(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "VERIFICATION",
                "RESET",
                name="tokenpurpose",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_email_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_email_tokens_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT", name="fk_email_tokens_user_id_users"
        ),
        sa.CheckConstraint(
            "token_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_email_tokens_token_hash_shape")
        ),
        sa.CheckConstraint("expires_at > created_at", name=op.f("ck_email_tokens_token_lifetime")),
    )
    op.create_index("ix_email_tokens_user_purpose", "email_tokens", ["user_id", "purpose"])
    op.create_table(
        "auth_throttles",
        *_record_columns(),
        sa.Column("bucket_hash", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_throttles"),
        sa.UniqueConstraint("bucket_hash", name="uq_auth_throttles_bucket_hash"),
        sa.CheckConstraint(
            "bucket_hash ~ '^[0-9a-f]{64}$'", name=op.f("ck_auth_throttles_bucket_hash_shape")
        ),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_auth_throttles_attempts_nonnegative")),
    )
    op.create_index("ix_auth_throttles_window", "auth_throttles", ["window_started_at"])
    op.execute("GRANT USAGE ON SCHEMA public TO reconcile_identity")
    for table in _AUTH_TABLES:
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(f'GRANT SELECT, INSERT, UPDATE ON "{table}" TO reconcile_identity')
        op.execute(
            f'CREATE TRIGGER touch_updated_at BEFORE UPDATE ON "{table}" '
            "FOR EACH ROW EXECUTE FUNCTION touch_updated_at()"
        )
    op.execute("GRANT SELECT, INSERT ON users TO reconcile_identity")
    op.execute("GRANT UPDATE (email_verified_at) ON users TO reconcile_identity")
    op.execute(
        "GRANT SELECT, INSERT ON organizations, organization_memberships TO reconcile_identity"
    )
    for table in (*_AUTH_TABLES, "users", "organizations", "organization_memberships"):
        op.execute(
            f'CREATE POLICY identity_access ON "{table}" TO reconcile_identity '
            "USING (true) WITH CHECK (true)"
        )


def downgrade() -> None:
    for table in ("users", "organizations", "organization_memberships"):
        op.execute(f'DROP POLICY identity_access ON "{table}"')
        op.execute(f'REVOKE ALL ON "{table}" FROM reconcile_identity')
    for table in reversed(_AUTH_TABLES):
        op.drop_table(table)
    op.drop_column("users", "email_verified_at")
    op.execute("REVOKE USAGE ON SCHEMA public FROM reconcile_identity")
