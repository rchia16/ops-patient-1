# OPS Patient 1 remote deployment checklist

This package is prepared for a Render Docker Web Service, Render Postgres, Auth0, and a Cloudflare-managed custom domain. Nothing in this source package provisions or deploys infrastructure, publishes a plugin, changes sharing, or replaces the currently installed plugin.

## Architecture

- Render runs the container and exposes `GET /health` plus the authenticated Streamable HTTP MCP endpoint at `POST /mcp`.
- Render Postgres stores sessions, ordered events, evidence, and image-disclosure state.
- Auth0 signs OAuth access tokens. The resource server validates the signature, issuer, audience, expiry, subject, and `simulation:use` scope.
- Cloudflare provides DNS for a stable hostname such as `mcp.example.com`. Keep proxying disabled until Render custom-domain verification and TLS issuance are complete; enable it later only after end-to-end testing.
- The opaque simulation `session_id` is used for continuity. The service does not claim access to a ChatGPT conversation ID.

## Before deployment

1. Choose the final hostname. Replace every `mcp.example.com` placeholder in `mcp.json`, `.mcp.json`, and environment values only after the hostname is attached and reachable.
2. In Auth0, create an API whose Identifier is the exact value used for `AUTH0_AUDIENCE`; add the delegated permission `simulation:use`.
3. Configure an Auth0 application suitable for the ChatGPT/OpenAI connector flow. Register the exact callback URLs shown by the product during connection setup. Use Authorization Code with PKCE; do not place a client secret in this package.
4. Ensure Auth0 access tokens contain a stable human-user `sub`. That validated `sub` is the sole session owner key. Never add `owner_id` to a tool schema or trust one supplied by a model.
5. Review the Render plan identifiers and costs in `render.yaml`; they are deliberately not provisioned by this package.

## Render setup

1. Create a Render Postgres database in Singapore.
2. Apply `migrations/001_initial.sql` using Render's database shell or your approved migration runner.
3. Create a Docker Web Service in Singapore from this source directory. The container listens on Render's `PORT`; set `/health` as the health path.
4. Attach the database's internal connection string as `DATABASE_URL`.
5. Configure the values shown in `.env.example` in Render's secret/environment settings. Do not commit real credentials or database URLs.
6. Set `OPS_PUBLIC_URL` to the final external URL including `/mcp`, for example `https://mcp.example.com/mcp`.
7. Attach the custom hostname in Render, add the Render-provided DNS target in Cloudflare, and wait for Render TLS verification.

## OAuth checks

- `AUTH0_ISSUER_URL` must be the tenant issuer, including `https://`.
- `AUTH0_AUDIENCE` must match the Auth0 API Identifier exactly.
- `AUTH0_JWKS_URL` may be omitted; it defaults to the issuer's standard JWKS endpoint.
- Tokens must be RS256-signed and include `iss`, `aud`, `iat`, `exp`, `sub`, plus `simulation:use` in `scope` or `permissions`.
- Requests without a valid token must receive `401`; tokens with the wrong issuer, audience, signature, expiry, or scope are rejected before tool code runs.

## Verification before changing the plugin connection

1. Confirm `GET /health` returns `200` without disclosing configuration or database details.
2. Run `python -m unittest discover -s tests -v` in an isolated environment.
3. Connect an MCP inspector using a valid Auth0 token and verify initialization, eight-tool discovery, valid and invalid calls, image content, persistence across requests, and feedback gates.
4. Use two Auth0 users to prove each can start a case and neither can access the other's `session_id` or evidence.
5. Confirm no endpoint, log, or tool result exposes the patient source path, image descriptions, bearer tokens, Auth0 configuration, or database credentials.
6. Replace the placeholder manifest URL with the tested custom-domain `/mcp` URL.

## Deliberately deferred

Do not upload this package, publish a new release, replace the installed plugin, or alter audience/sharing until the deployment is verified and the owner explicitly approves those actions.
