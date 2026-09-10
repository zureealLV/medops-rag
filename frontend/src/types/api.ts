export type AuthMode = 'trusted_headers' | 'api_key'

export interface ConnectionProfile {
  authMode: AuthMode
  tenantId: string
  actorId: string
  apiKey: string
}

export interface Health {
  status: string
  version: string
  database: string
}

export interface Identity {
  tenant_id: string
  actor: string
  role: string
  credential_id: string | null
  auth_mode: string
}

export interface KnowledgeBase {
  id: number
  tenant_id: string
  name: string
  description: string | null
}

export interface DocumentSummary {
  id: number
  kb_id: number
  tenant_id: string
  title: string
  source: string
  chunk_count: number
  element_count: number
  artifact_count: number
  mime_type: string
  parser: string
  ingest_status: string
}

export interface DocumentPage {
  items: DocumentSummary[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface Evidence {
  score: number
  source: string
  document_id: number
  chunk_id: number
  text: string
  matched_text?: string | null
  page_start?: number | null
  page_end?: number | null
  heading?: string | null
}

export type RetrievalStrategy = 'auto' | 'keyword' | 'vector' | 'weighted' | 'bm25' | 'rrf' | 'parent_child'
export type QueryTransform = 'auto' | 'none' | 'rewrite' | 'multi_query' | 'hyde'
export type RetrievalProfile = 'auto' | 'text' | 'visual'
export type VisualStrategy = 'ocr' | 'image' | 'fusion'
export type OrchestrationEngine = 'classic' | 'langchain' | 'langgraph'

export interface SearchRequest {
  query: string
  knowledge_base_id: number
  top_k: number
  strategy: RetrievalStrategy
  query_transform: QueryTransform
}

export interface SearchResponse {
  query: string
  strategy: RetrievalStrategy
  results: Evidence[]
  retrieval_ms: number
  query_transform: QueryTransform
  transformed_queries: string[]
  routing: AdaptiveRoutingTrace | null
}

export interface AdminAnswerRequest {
  question: string
  knowledge_base_id: number
  top_k: number
  retrieval_profile: RetrievalProfile
  text_strategy: RetrievalStrategy
  query_transform: QueryTransform
  visual_strategy: VisualStrategy
  orchestration: OrchestrationEngine
}

export interface Citation {
  source: string
  document_id: number
  chunk_id: number
  parent_id: number | null
}

export interface VisualCitation {
  artifact_id: number
  source: string
  document_id: number
  page_number: number | null
  content_url: string
  sha256: string
}

export interface AgentStep {
  node: string
  status: 'completed' | 'abstained' | 'failed'
  duration_ms: number
  detail: string | null
}

export interface AdaptiveRoutingTrace {
  strategy: 'bm25' | 'rrf' | 'parent_child'
  reason_code: string
  reason: string
  confidence: number
  features: Record<string, number | boolean>
  candidate_scores: Record<string, number>
}

export interface AnswerResponse {
  answer: string
  citations: Citation[]
  visual_citations: VisualCitation[]
  retrieved_chunks: Evidence[]
  retrieved_artifacts: VisualEvidence[]
  retrieval_profile: 'text' | 'visual'
  retrieval_strategy: string | null
  retrieval_routing: AdaptiveRoutingTrace | null
  query_transform: QueryTransform
  transformed_queries: string[]
  abstained: boolean
  reason: string | null
  provider: string
  retrieval_ms: number
  model_ms: number
  token_usage: number
  prompt_tokens: number
  completion_tokens: number
  cached_prompt_tokens: number
  orchestration: OrchestrationEngine
  agent_steps: AgentStep[]
}

export interface VisualEvidence extends VisualCitation {
  score: number
  ocr_score: number
  image_score: number | null
  image_similarity: number | null
  mime_type: string
  width: number
  height: number
  ocr_text: string
  metadata: Record<string, string | number | boolean | null>
  embedding_model: string | null
}

export interface QueueMetric {
  states: Record<string, number>
  oldest_queued_age_seconds: number
}

export interface Metrics {
  generated_at: string
  window_hours: number
  tenant_id: string
  queues: Record<string, QueueMetric>
  requests: {
    count: number
    error_count: number
    abstained_count: number
    latency_ms: { avg: number; p95: number }
    retrieval_ms_p95: number
    model_ms_p95: number
    token_usage: number
    providers: Record<string, number>
    fallback_count: number
  }
  pipeline_stages: Record<string, { count: number; error_count: number; avg_ms: number; p95_ms: number }>
  pipeline_providers: Record<string, number>
  rag_routing: {
    event_count: number
    strategies: Record<string, number>
    reasons: Record<string, number>
    orchestrations: Record<string, number>
    overload_rejections: number
    overload_reasons: Record<string, number>
    circuit_rejections: number
    circuit_states: Record<string, number>
    deadline_rejections: number
    deadline_phases: Record<string, number>
    malformed_audit_details: number
  }
  provider_runtime: {
    scope: 'process_local'
    capacity: {
      active: number
      waiting: number
      active_tenants: number
      outstanding: number
      max_concurrency: number
      max_concurrency_per_tenant: number
      max_queue_waiters: number
      max_queue_waiters_per_tenant: number
    }
    circuit: {
      state: 'closed' | 'open' | 'half_open'
      consecutive_failures: number
      epoch: number
      half_open_probe_active: boolean
    }
    policy: {
      request_deadline_seconds: number
      max_retries_per_request: number
      retry_after_max_seconds: number
    }
    retry_budget: {
      retries_consumed: number
      global: {
        remaining: number
        capacity: number
        refill_per_second: number
        rejected: number
      }
      per_tenant: {
        tracked: number
        remaining_total: number
        remaining_min: number | null
        remaining_max: number | null
        capacity: number
        refill_per_second: number
        rejected: number
      }
    }
  }
}
