# MedOps Web Console V2.3

The first-party, same-origin browser interface lives at `/ui/`; `/` redirects there. V2.3 keeps the bright white/teal clinical theme, prefers the Chinese Huatuo research knowledge base on a fresh session, and presents citations as numbered source cards without raw retrieval scores. Static HTML, CSS and JavaScript are served by FastAPI, so the demonstration has no Node.js runtime or frontend build chain.

## Demonstrated workflows

- view service health and the running application version;
- list tenant-scoped knowledge bases and documents;
- create a knowledge base;
- upload a supported document through the synchronous demonstration endpoint;
- ask a text or visual question and inspect the answer, abstention reason, timing and evidence;
- inspect 24-hour request, latency, abstention, fallback and worker-queue metrics;
- open the generated Swagger UI for lower-level API exploration.

## Start and open

```powershell
.\.venv\Scripts\python.exe .\scripts\seed_sample_data.py --profile medical
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/`.

The default local profile sends `X-Tenant-ID: hospital-a` and `X-Actor-ID: zureealLV`. The connection dialog can instead send a Bearer API key when the server itself is running with `AUTH_MODE=api_key`.

## Security and scope boundary

- The console is an operator demonstration surface, not an authorization boundary. The API remains responsible for identity, role and tenant enforcement.
- Bearer keys are held in `sessionStorage`, not `localStorage`, and are not printed into the activity log.
- Visual evidence is fetched with the active authorization headers rather than exposed through an unauthenticated image URL.
- All dynamic HTML values are escaped before insertion. Artifact URLs are restricted to the current origin.
- The synchronous upload action is optimized for an immediate local demo. Durable ingestion jobs and workers remain the production-shaped path for queued ingestion.
- Only synthetic, public, licensed, de-identified healthcare or medical-device material belongs in this portfolio application. It is not a medical device and must not contain real patient records.

## Deployment note

The Docker image copies `web/` into `/app/web`, and the FastAPI application serves it from the same origin as the API. A reverse proxy therefore needs no additional static-site route; it should forward `/`, `/ui/*` and API paths to the FastAPI service.
