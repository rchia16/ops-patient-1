# Verification record — 9 October 2026

Command:

```text
python -m unittest discover -s tests -v
```

Result: **30 tests passed** with the dependencies pinned in `requirements.txt`.

Coverage includes:

- official Streamable HTTP MCP initialization and exact discovery of all eight tools;
- rejection of unauthenticated requests and invalid tool arguments;
- Auth0-compatible RS256 validation for signature, issuer, audience, expiry, scope, and subject;
- authenticated session persistence across independent HTTP requests;
- cross-owner session isolation and rejection of model-supplied `owner_id`;
- deterministic history and examination results, laterality, conflict detection, source changes, and missing data;
- actual MCP PNG image content with base64 removed from structured metadata;
- evidence-bound output validation and persistent image disclosure state;
- the two-stage end/explicit-feedback gate and chat-only feedback context;
- preservation of source images, evaluator, manual, and patient-role behavior.

The test suite uses an explicit temporary SQLite development database. Production is configured through PostgreSQL-compatible SQL and `DATABASE_URL`; `migrations/001_initial.sql` is the production migration. A live Render/Postgres/Auth0/Cloudflare deployment has not been created or tested because deployment was explicitly excluded from this task.

Before attaching a future deployment to the plugin, repeat the checklist in `DEPLOYMENT.md` against the real endpoint with two separate Auth0 users.
