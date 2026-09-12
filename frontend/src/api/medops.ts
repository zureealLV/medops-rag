import { apiRequest, encodeQuery } from './client'
import type {
  AdminAnswerRequest,
  AnswerResponse,
  ConversationDetail,
  ConversationSummary,
  ConversationTurnResponse,
  DocumentPage,
  Health,
  Identity,
  KnowledgeBase,
  Metrics,
  ManagedUser,
  ModelConfigInput,
  ModelConfigTestResult,
  ModelConfigView,
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
  listConversations: () => apiRequest<ConversationSummary[]>('/conversations'),
  createConversation: (data: { knowledge_base_id: number; title?: string }) =>
    apiRequest<ConversationSummary>('/conversations', { method: 'POST', body: JSON.stringify(data) }),
  getConversation: (id: string) => apiRequest<ConversationDetail>(`/conversations/${id}`),
  deleteConversation: (id: string) => apiRequest<void>(`/conversations/${id}`, { method: 'DELETE' }),
  sendConversationMessage: (id: string, content: string, signal?: AbortSignal) =>
    apiRequest<ConversationTurnResponse>(`/conversations/${id}/messages`, {
      method: 'POST', body: JSON.stringify({ content }), signal,
    }),
  listUsers: () => apiRequest<ManagedUser[]>('/users'),
  createUser: (data: { name: string; email: string }) =>
    apiRequest<ManagedUser>('/users', { method: 'POST', body: JSON.stringify(data) }),
  adminAnswer: (data: AdminAnswerRequest, signal?: AbortSignal) =>
    apiRequest<AnswerResponse>('/answer', { method: 'POST', body: JSON.stringify(data), signal }),
  search: (data: SearchRequest, signal?: AbortSignal) =>
    apiRequest<SearchResponse>('/search', { method: 'POST', body: JSON.stringify(data), signal }),
  metrics: () => apiRequest<Metrics>('/system/metrics'),
  modelConfig: () => apiRequest<ModelConfigView>('/system/model-config'),
  applyModelConfig: (data: ModelConfigInput) =>
    apiRequest<ModelConfigView>('/system/model-config', { method: 'PUT', body: JSON.stringify(data) }),
  testModelConfig: (data: ModelConfigInput) =>
    apiRequest<ModelConfigTestResult>('/system/model-config/test', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  mcpInitialize: () => apiRequest<McpInitializeResponse>('/mcp/', {
    method: 'POST',
    headers: {
      Accept: 'application/json, text/event-stream',
      'Mcp-Protocol-Version': '2025-11-25',
    },
    body: JSON.stringify({
      jsonrpc: '2.0',
      id: 1,
      method: 'initialize',
      params: {
        protocolVersion: '2025-11-25',
        capabilities: {},
        clientInfo: { name: 'medops-console', version: '3.5.0' },
      },
    }),
  }),
  mcpListTools: () => apiRequest<McpToolsResponse>('/mcp/', {
    method: 'POST',
    headers: {
      Accept: 'application/json, text/event-stream',
      'Mcp-Protocol-Version': '2025-11-25',
    },
    body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list', params: {} }),
  }),
}

export interface McpInitializeResponse {
  result: {
    protocolVersion: string
    serverInfo: { name: string; version: string; description?: string }
  }
}

export interface McpToolsResponse {
  result: {
    tools: Array<{ name: string; description: string; inputSchema: Record<string, unknown> }>
  }
}
