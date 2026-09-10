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
  retrieval_profile: 'text' | 'visual'
  retrieval_strategy: string | null
  retrieval_routing: AdaptiveRoutingTrace | null
  abstained: boolean
  reason: string | null
  provider: string
  retrieval_ms: number
  model_ms: number
  token_usage: number
  prompt_tokens: number
  completion_tokens: number
  cached_prompt_tokens: number
  agent_steps: AgentStep[]
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
}
