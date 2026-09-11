# V2 API-key Authentication and Authorization

Status: implemented and covered by `tests/test_authentication.py`.

## Modes and trust boundaries

`AUTH_MODE=trusted_headers` is the default development profile. It accepts `X-Tenant-ID` and
`X-Actor-ID` only when a trusted local reverse proxy or developer controls every caller. It preserves the
low-friction demo workflow and must not be exposed directly to hostile clients.

`AUTH_MODE=api_key` is the hardened service profile. Every protected endpoint requires
`Authorization: Bearer <key>`. The server looks up the tenant, actor and role from SQLite and ignores caller
supplied tenant/actor headers. `/health` remains public so an orchestrator can probe the process.

## Credential format and storage

Keys have the form `mops_<12 hexadecimal characters>.<random secret>`. The prefix is a lookup identifier;
it grants no access by itself. The database stores only a random 16-byte salt and a 32-byte scrypt-derived
secret hash (`N=16384`, `r=8`, `p=1`). The plaintext key is printed once when it is created and cannot be
recovered. Revocation is immediate because each request verifies the active database row without a cache.

Create and revoke credentials from a trusted shell rather than an unauthenticated bootstrap endpoint:

```powershell
$env:DATABASE_URL = "sqlite:///./data/medops.db"
.\.venv\Scripts\python.exe .\scripts\manage_api_keys.py create `
  --tenant hospital-a --name local-admin --role admin

.\.venv\Scripts\python.exe .\scripts\manage_api_keys.py revoke `
  --tenant hospital-a --id <credential-id>
```

Set `AUTH_MODE=api_key`, start the API, and send the printed value:

```powershell
$headers = @{ Authorization = "Bearer mops_<prefix>.<secret>" }
Invoke-RestMethod http://127.0.0.1:8000/auth/whoami -Headers $headers
```

## Roles

| Role | Allowed operations |
|---|---|
| `viewer` | all `GET` requests plus read-only query calls to `/search`, `/visual-search`, `/answer` and `/tools/call` |
| `editor` | viewer operations plus knowledge-base, document, ingestion-job and summary-job mutations |
| `admin` | all operations, including `/users` and `/audit-logs` |

Authorization runs in the shared tenant-context dependency before route business logic. Repository queries
still include `tenant_id`, providing defense in depth and hidden `404` behavior for foreign resource IDs.

## Deliberate limits

- API keys are service credentials, not interactive user sessions; there is no password, OIDC, MFA or key
  self-service flow.
- There is no distributed rate limiter. A public deployment must put TLS, request limits and abuse controls
  at the gateway because scrypt verification intentionally consumes CPU.
- The SQLite credential store targets the selected single-host profile. Multi-host deployment needs a shared
  identity store and a tested revocation propagation model.
- Key creation output can leak through shell history or CI logs. Generate keys only in an appropriate trusted
  terminal and move them to a secret manager immediately.
