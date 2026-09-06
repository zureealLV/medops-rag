# MedOps Multimodal RAG V2 Threat Model

## Assets and trust boundaries

Protected assets are tenant documents, model credentials, audit integrity and service availability. External request bodies, tenant headers, ingested documents, model responses and tool arguments are untrusted. SQLite, application policy and the tool registry are inside the demonstration boundary.

`X-Tenant-ID` is assumed to be supplied by a trusted upstream gateway. V2 alpha does not authenticate it, so exposing this service directly to hostile clients would break that assumption.

| Threat | Entry | Alpha control | Test evidence | Residual risk |
|---|---|---|---|---|
| Tenant data leak | forged KB/document ID or search | tenant predicate in repository SQL before ranking/model context; hidden `404` | `tests/test_tenant_isolation.py` | header is not authenticated in V1 |
| Indirect prompt injection | malicious ingested text | retrieved text marked untrusted; suspicious chunks quarantined; no tools exposed to answer generator | `tests/test_prompt_injection.py` | heuristic patterns can miss novel attacks |
| Tool abuse | arbitrary tool name/arguments | three read-only tools; Pydantic validation; no shell/email/delete capability | `tests/test_tools.py` | production tools need per-user authorization and rate limits |
| Secret/PII leakage | query, audit or exception text | `.env` ignored; audit details redacted; raw document content not logged | `tests/test_pii_redaction.py` | regex redaction cannot identify every sensitive format |
| Hallucination | weak or absent evidence | evidence threshold, abstention and citations derived from retrieved rows | `tests/test_answers.py` | a model can still misinterpret valid evidence |
| Availability loss | slow/unavailable model | request timeout, bounded retry and offline fallback | `app/agents/model.py` | no distributed rate limiter or circuit breaker |
| Unsafe medical advice | user asks for diagnosis/treatment | policy refusal before retrieval/model call | `tests/test_answers.py` | intent classifier is deliberately simple |
| Resource exhaustion | oversized upload or decoded raster | independent byte and decoded-pixel limits before OCR | `tests/test_multimodal_ingestion.py` | office archive expansion and per-page PDF render budgets remain beta work |
| Malformed parser input | corrupt PDF/Office/image container | parser-specific stable 4xx errors; no document row is committed | `tests/test_multimodal_ingestion.py` | third-party parser vulnerabilities require isolation and fuzzing |
| OCR poisoning | misleading text embedded in screenshots/scans | OCR output remains untrusted document data and passes the same retrieval/injection policy | parser and prompt-injection tests | visual prompt injection and adversarial images need dedicated V2 cases |
| Cross-tenant byte deduplication | identical document uploaded by different tenants | SHA-256 uniqueness is scoped by tenant and knowledge base | `tests/test_multimodal_ingestion.py`, tenant tests | a future global artifact store must preserve tenant authorization |

## Data flow

```text
request + trusted tenant context
  -> validation and policy
  -> tenant-filtered SQLite retrieval
  -> injection quarantine
  -> evidence threshold
  -> optional model / offline fallback
  -> citations + redacted audit event
```

## Non-claims

V2 is not HIPAA, GDPR, PIPL or medical-device compliance evidence. It does not claim complete prompt-injection prevention, production authentication, clinical correctness or hospital-scale availability. Alpha.1 OCR support is not yet full chart/diagram reasoning or visual prompt-injection protection.
