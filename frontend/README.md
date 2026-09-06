# Reconciliation frontend

The frontend is a stateless Next.js interface for the repository's FastAPI reconciliation API.

Create local configuration from `.env.example`, then run:

```bash
npm install
npm run dev
```

The backend must allow the frontend's exact origin through `RECONCILE_ALLOWED_ORIGINS`. See the
root README for the complete two-server development setup and verification commands.
