# OPS Patient 1 — remote source package, version 1.2.0

This is a source-only update of the existing private OPS Patient 1 plugin. It converts the local Python stdio server to an authenticated, device-independent Streamable HTTP MCP service while preserving the plugin identity, audience, eight tool contracts, case behavior, source case, images, patient-role skill, session log, and post-session feedback gates.

Nothing in this package provisions infrastructure, deploys a service, publishes a release, changes sharing, or replaces the installed plugin.

## Runtime design

| Concern | Implementation |
|---|---|
| MCP transport | Official Python MCP SDK, stateless Streamable HTTP at `/mcp` |
| Authentication | Auth0 RS256 access tokens; signature, issuer, audience, expiry, subject, and `simulation:use` scope are validated |
| Ownership | Every simulation session is bound to the validated token `sub`; `owner_id` is not a tool argument |
| Continuity | Opaque simulation `session_id`; no assumption that a ChatGPT conversation ID is available |
| Persistence | PostgreSQL in production through `DATABASE_URL`; SQLite remains available only when an explicit development/test database is supplied |
| Hosting target | Render Docker Web Service and Render Postgres in Singapore, with Cloudflare-managed DNS |
| Health | Unauthenticated `GET /health`; no configuration or database data is exposed |
| Feedback | Evaluation remains locked until the case ends and an explicit post-end user feedback request is logged; output remains chat-only and generates no PDF |

The root `mcp.json` and compatibility `.mcp.json` intentionally contain `https://mcp.example.com/mcp`. That is a placeholder, not a live service. Replace it only after the real custom-domain endpoint has been deployed and verified.

## Structure

```text
ops-patient-1/
  plugin.json
  .codex-plugin/plugin.json
  mcp.json
  .mcp.json
  Dockerfile
  render.yaml
  .env.example
  DEPLOYMENT.md
  migrations/001_initial.sql
  requirements.txt
  schemas/{case.schema.json,tools.json}
  server/{mcp_server.py,auth.py,backend.py,storage.py,case_adapter.py,validation.py,host_gateway.py,run.py}
  skills/patient-role/
  data/
  source-originals/
  tests/{test_backend.py,test_remote.py}
```

`source-originals/` contains audit inputs, not executable skills. The local package owner can inspect the case files; confidentiality applies to the patient-role tool surface, not to someone who owns the source package.

## Development verification

Use Python 3.10 or newer. On Windows:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

On macOS or Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

For a local development server, copy `.env.example` to an untracked `.env`, set real development values, set `DATABASE_URL` to an explicit SQLite path such as `sqlite:///./dev.sqlite3`, and run `python server/run.py`. Do not use development tokens or SQLite for production.

## Tool contracts

`schemas/tools.json` remains the machine-readable source of the exact eight input schemas. Extra properties are rejected, including any model-supplied `owner_id`.

| Tool | Purpose |
|---|---|
| `load_case` | Validate the authoritative case and images and create one active owner-bound session |
| `get_patient_fact` | Return only allowlisted history facts through canonical templates |
| `get_test_result` | Return factual, laterality-aware `[NURSE]` examination results |
| `get_linked_image` | Return actual PNG MCP image content without image descriptions or interpretations |
| `record_interaction` | Persist ordered user/assistant interaction data and explicit feedback requests |
| `validate_response` | Verify exact evidence-bound response templates before display |
| `end_case` | End role-play idempotently without automatic evaluation |
| `evaluate_case` | Release feedback context only after both feedback gates pass |

The server does not diagnose, interpret images, expose image descriptions, invent missing results, or expose hidden case metadata during role-play. Image disclosure state and evidence remain session-bound and owner-isolated.

## Security boundary

The remote transport rejects unauthenticated requests before tool execution. The service derives the owner solely from a verified token subject and applies that owner filter when loading or ending a session. Session IDs are opaque routing values, not credentials. A second authenticated user cannot access the first user's session or evidence even if a session ID is known.

Tool arguments still include the preserved `interaction.actor` field. The host must supply correct turn provenance, as documented in the original contract; a tool argument alone cannot cryptographically prove who authored text. The output-gate adapter remains available for hosts that can enforce before-display validation.

See [DEPLOYMENT.md](DEPLOYMENT.md) for the Render, Auth0, and Cloudflare checklist. Deployment and plugin replacement are deliberately deferred pending explicit owner approval.
