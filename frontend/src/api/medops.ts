import { apiRequest, encodeQuery } from './client'
import type {
  AdminAnswerRequest,
  AnswerResponse,
  DocumentPage,
  Health,
  Identity,
  KnowledgeBase,
  Metrics,
  SearchRequest,
  SearchResponse,
} from '@/types/api'

export const medopsApi = {
  health: () => apiRequest<Health>('/health'),
  whoami: () => apiRequest<Identity>('/auth/whoami'),
  listKnowledgeBases: () => apiRequest<KnowledgeBase[]>('/knowledge-bases'),
  createKnowledgeBase: (data: { name: string; description: string | null }) =>
    apiRequest<KnowledgeBase>('/knowledge-bases', { method: 'POST', body: JSON.stringify(data) }),
  listDocuments: (kbId: number, options: { limit: number; offset: number; query: string }, signal?: AbortSignal) =>
    apiRequest<DocumentPage>(`/knowledge-bases/${kbId}/documents/page?${encodeQuery(options)}`, { signal }),
  uploadDocument: (kbId: number, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return apiRequest(`/knowledge-bases/${kbId}/documents/upload`, { method: 'POST', body })
  },
  answer: (data: { question: string; knowledge_base_id: number; top_k: number }, signal?: AbortSignal) =>
    apiRequest<AnswerResponse>('/answer', { method: 'POST', body: JSON.stringify(data), signal }),
  adminAnswer: (data: AdminAnswerRequest, signal?: AbortSignal) =>
    apiRequest<AnswerResponse>('/answer', { method: 'POST', body: JSON.stringify(data), signal }),
  search: (data: SearchRequest, signal?: AbortSignal) =>
    apiRequest<SearchResponse>('/search', { method: 'POST', body: JSON.stringify(data), signal }),
  metrics: () => apiRequest<Metrics>('/system/metrics'),
}
