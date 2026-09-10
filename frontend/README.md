# Reconciliation frontend

The Next.js interface uses cookie-backed authentication and organization-scoped FastAPI analyses.
Raw financial files remain temporary. Browser analyses save validated evidence and report snapshots
to PostgreSQL. `/history` provides filtered, paginated history; `/history/{id}` shows the original
report, provenance, and permission-controlled metadata/archive/restore actions. There is no
stateless fallback or automatic create retry: check History after an uncertain submission.

Create local configuration from `.env.example`, then run:

```bash
npm ci
npm run dev -- --hostname 127.0.0.1
```

The backend must allow the frontend's exact origin through `RECONCILE_ALLOWED_ORIGINS`. See the
root README for the complete two-server development setup and verification commands.

Open `http://127.0.0.1:3000` with the default API origin `http://127.0.0.1:8000`; do not mix
`localhost` and `127.0.0.1`. Authenticated browser tests need `TEST_DATABASE_ADMIN_URL` and all
backend extras. Build with the E2E API origin (`http://127.0.0.1:8010` by default), then run
`npm run test:e2e`. Playwright starts the production frontend and a real authenticated API backed
by its own disposable database. See the root database guide for provisioning and cleanup.
