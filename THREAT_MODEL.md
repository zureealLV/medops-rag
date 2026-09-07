# MedOps Multimodal RAG V2 Threat Model

## Assets and trust boundaries

Protected assets are tenant documents, original image artifacts, derived embeddings, API/model credentials, audit integrity and service availability. External request bodies, tenant headers, ingested documents, model responses and tool arguments are untrusted. SQLite, application policy and the tool registry are inside the service boundary.

`AUTH_MODE=trusted_headers` assumes a trusted upstream gateway. `AUTH_MODE=api_key` instead resolves tenant,
actor and role from a salted scrypt hash record and ignores the untrusted identity headers. Neither mode
replaces gateway TLS, rate limiting or secret management.

| Threat | Entry | Alpha control | Test evidence | Residual risk |
|---|---|---|---|---|
| Credential/tenant spoofing | forged API key, identity header or resource ID | salted scrypt hash, constant-time comparison, revocation, server-bound tenant/role, tenant predicate before ranking/model context and hidden `404` | `tests/test_authentication.py`, `tests/test_tenant_isolation.py` | trusted-header mode remains forgeable without a gateway; no distributed rate limiter |
| Indirect prompt injection | malicious ingested text | retrieved text marked untrusted; suspicious chunks quarantined; no tools exposed to answer generator | `tests/test_prompt_injection.py` | heuristic patterns can miss novel attacks |
| Tool abuse | arbitrary tool name/arguments | three read-only tools; Pydantic validation; no shell/email/delete capability | `tests/test_tools.py` | production tools need per-user authorization and rate limits |
| Secret/PII leakage | query, audit or exception text | `.env` ignored; audit details redacted; raw document content not logged | `tests/test_pii_redaction.py` | regex redaction cannot identify every sensitive format |
| Hallucination | weak or absent evidence | normalized rank threshold plus absolute lexical/dense evidence floors, abstention and citations derived from retrieved rows | `tests/test_answers.py`, `reports/confidence-calibration-v2.json` | synthetic-set calibration does not transfer automatically; a model can still misinterpret valid evidence |
| Availability loss | slow/unavailable model | request timeout, bounded retry and offline fallback | `app/agents/model.py` | no distributed rate limiter or circuit breaker |
| Unsafe medical advice | user asks for diagnosis/treatment | policy refusal before retrieval/model call | `tests/test_answers.py` | intent classifier is deliberately simple |
| Resource exhaustion | oversized upload, Office ZIP bomb or oversized PDF/raster render | byte/pixel/page limits plus central-directory entry, expansion, per-entry and compression-ratio gates before decompression/OCR | `tests/test_multimodal_ingestion.py`, `tests/test_parser_security.py` | parser calls still share the worker OS account; no hard memory cgroup outside Compose |
| Malformed parser input | corrupt PDF/Office/image container, traversal entry or macro payload | deterministic malformed-byte corpus, stable 4xx errors, unsafe path/macro rejection; no document row is committed | `tests/test_parser_security.py` | deterministic fuzz cases do not replace continuous coverage-guided fuzzing of third-party libraries |
| Duplicate/background execution | API retry, expired lease or crashed worker | tenant-scoped idempotency key, SHA-256 document uniqueness, lease-owner fencing and three-attempt bound | `tests/test_ingestion_jobs.py` | SQLite queue is for local deployment; cancellation during a blocking parser call is cooperative |
| Poison ingestion job | permanently unsupported or malformed input | stable parser failures become terminal without retry; transient worker exceptions are bounded and visible | `tests/test_ingestion_jobs.py` | parser process sandboxing and resource quotas remain V2 hardening work |
| Summary prompt injection | instructions embedded in selected documents or map output | summary prompts label data untrusted, expose no tools, cap document/map characters and retain document citations | `tests/test_summary_jobs.py` | model-level instruction following cannot be fully prevented by prompt text |
| Lost/duplicated summary work | worker crash or concurrent claims | fenced lease, persisted per-document map result, heartbeat, idempotent result key and resumable reduce | `tests/test_summary_jobs.py` | SQLite remains a single-host queue |
| OCR poisoning | misleading text embedded in screenshots/scans | OCR output remains untrusted document data and passes the same retrieval/injection policy | parser and prompt-injection tests | visual prompt injection and adversarial images need dedicated V2 cases |
| Visual prompt injection | instructions rendered inside an image sent to a VLM | visual content is labeled untrusted; no tools are exposed; image transfer is opt-in; count and aggregate-byte caps apply | `tests/test_multimodal_answers.py` | a VLM can still follow adversarial pixels or misread the image |
| Excessive model payload | many/large retrieved images | `MODEL_MAX_VISUAL_IMAGES` and `MODEL_MAX_VISUAL_BYTES`; answer abstains if accepted evidence cannot be loaded safely | `tests/test_multimodal_answers.py` | remote providers may impose lower encoded-request limits |
| Artifact ID enumeration | forged artifact/reference ID | metadata and byte endpoints join through a tenant-owned document; foreign IDs return hidden `404` | `tests/test_visual_artifacts.py` | external object-store policy must preserve the same tenant predicate |
| Cross-tenant byte deduplication | identical image uploaded by different tenants | image BLOB uniqueness is `(tenant_id, sha256)`; no cross-tenant existence signal | `tests/test_visual_artifacts.py` | object-storage migration must preserve tenant-local namespaces |
| Embedding leakage | image vector from another tenant enters ranking | artifact retrieval rows filter document tenant in SQL before cosine scoring | `tests/test_visual_artifacts.py` | approximate external indexes require payload-filter tests |
| Model supply chain | first-use model download is replaced or unavailable | exact model IDs, isolated cache path, opt-in feature, no model files committed | smoke and benchmark scripts | model revision hashes and offline packaging remain release work |

## Data flow

```text
request + authenticated or trusted-gateway tenant context
  -> validation and policy
  -> tenant-filtered SQLite retrieval
  -> injection quarantine
  -> evidence threshold
  -> bounded tenant-scoped image loading
  -> optional text/vision model / offline locator fallback
  -> citations + redacted audit event
```

## Non-claims

V2 is not HIPAA, GDPR, PIPL or medical-device compliance evidence. API-key mode is a tested service-credential
boundary, not OIDC/MFA or an Internet-edge security stack. It does not claim complete prompt-injection
prevention, clinical correctness or hospital-scale availability. Alpha.2 text-to-image retrieval is not
chart/diagram reasoning, Chinese production quality or visual prompt-injection protection.
