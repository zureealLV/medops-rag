<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ChatDotRound, Delete, Plus, Promotion } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import AgentTrace from '@/components/AgentTrace.vue'
import CitationCard from '@/components/CitationCard.vue'
import { medopsApi } from '@/api/medops'
import { useAppStore } from '@/stores/app'
import type { ConversationDetail, ConversationSummary } from '@/types/api'

const app = useAppStore()
const conversations = ref<ConversationSummary[]>([])
const active = ref<ConversationDetail | null>(null)
const draft = ref('')
const loading = ref(false)
const messagesPanel = ref<HTMLElement | null>(null)
let controller: AbortController | null = null

const selectedKbId = computed({
  get: () => app.activeKbId,
  set: (value) => { app.activeKbId = value },
})

async function refreshList() { conversations.value = await medopsApi.listConversations() }
async function openConversation(id: string) {
  active.value = await medopsApi.getConversation(id)
  app.activeKbId = active.value.knowledge_base_id
  await scrollToBottom()
}

async function newConversation() {
  if (!selectedKbId.value) return ElMessage.warning('请先选择知识库')
  const created = await medopsApi.createConversation({ knowledge_base_id: selectedKbId.value })
  await refreshList()
  await openConversation(created.id)
  draft.value = ''
}

async function removeConversation(id: string) {
  await ElMessageBox.confirm('将删除该对话及全部消息，此操作不可撤销。', '删除对话', { type: 'warning' })
  await medopsApi.deleteConversation(id)
  if (active.value?.id === id) active.value = null
  await refreshList()
}

async function send() {
  const content = draft.value.trim()
  if (content.length < 2) return
  if (!active.value) await newConversation()
  if (!active.value) return
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  draft.value = ''
  active.value.messages.push({ id: -Date.now(), role: 'user', content, contextualized_question: null, answer: null, created_at: new Date().toISOString() })
  await scrollToBottom()
  try {
    const result = await medopsApi.sendConversationMessage(active.value.id, content, controller.signal)
    app.log('持续对话', result.answer.abstained ? 'ABSTAINED' : 'CITED')
    await Promise.all([openConversation(active.value.id), refreshList()])
  } catch (error) {
    draft.value = content
    await openConversation(active.value.id)
    if ((error as Error).name !== 'AbortError') ElMessage.error(`回答失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally { loading.value = false }
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void send() }
}

async function scrollToBottom() {
  await nextTick()
  messagesPanel.value?.scrollTo({ top: messagesPanel.value.scrollHeight, behavior: 'smooth' })
}

watch(() => app.activeKbId, async (next, previous) => {
  if (next && previous && next !== previous && active.value?.knowledge_base_id !== next) active.value = null
})

onMounted(async () => {
  await refreshList()
  if (conversations.value[0]) await openConversation(conversations.value[0].id)
})
onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="conversation-workspace">
    <aside class="conversation-sidebar">
      <header><p>MEDOPS CHAT</p><h2>智能问答</h2><small>彩色知识对话台</small></header>
      <el-select v-model="selectedKbId" placeholder="选择知识库" class="kb-picker">
        <el-option v-for="kb in app.knowledgeBases" :key="kb.id" :label="kb.name" :value="kb.id" />
      </el-select>
      <button class="new-chat-button" type="button" @click="newConversation"><el-icon><Plus /></el-icon>新对话</button>
      <div class="history-label"><span>对话记录</span><b>{{ conversations.length }}</b></div>
      <div class="conversation-list">
        <button v-for="item in conversations" :key="item.id" :class="{ active: active?.id === item.id }" type="button" @click="openConversation(item.id)">
          <el-icon><ChatDotRound /></el-icon><span><b>{{ item.title }}</b><small>{{ item.message_count }} 条消息</small></span>
          <el-icon class="delete-chat" @click.stop="removeConversation(item.id)"><Delete /></el-icon>
        </button>
        <p v-if="!conversations.length" class="no-history">还没有对话，问点什么吧。</p>
      </div>
    </aside>

    <section class="chat-stage">
      <header class="chat-stage-header">
        <div><h1>智能问答</h1><p><i />LangGraph 多轮记忆 · 自动智能体路由</p></div>
        <span class="window-dots"><i /><i /><i /></span>
      </header>
      <div ref="messagesPanel" class="chat-messages">
        <div v-if="!active || !active.messages.length" class="chat-empty">
          <div class="empty-cube"><i /><i /><i /></div>
          <h3>从一个不必完美的问题开始</h3>
          <p>口语、错别字、“那它呢”这样的追问都可以。</p>
          <div class="prompt-chips"><button @click="draft='血氧仪为啥有时候测不准？'">血氧仪为啥测不准？</button><button @click="draft='这个东西有啥使用限制？'">这东西有啥限制？</button></div>
        </div>
        <article v-for="message in active?.messages ?? []" :key="message.id" :class="['chat-message', message.role]">
          <div class="message-avatar">{{ message.role === 'user' ? '我' : 'M' }}</div>
          <div class="message-body">
            <div class="message-meta"><b>{{ message.role === 'user' ? '你' : 'MedOps Agent' }}</b><time>{{ new Date(message.created_at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) }}</time></div>
            <div class="message-copy">{{ message.content }}</div>
            <template v-if="message.answer">
              <div class="answer-badges"><el-tag :type="message.answer.abstained ? 'warning' : 'success'">{{ message.answer.abstained ? '安全拒答' : '证据已核验' }}</el-tag><span>{{ message.answer.orchestration }} · {{ (message.answer.retrieval_ms + message.answer.model_ms).toFixed(0) }} ms</span></div>
              <details v-if="message.answer.citations.length" class="message-evidence"><summary>查看 {{ message.answer.citations.length }} 条引用来源</summary><div class="citation-grid"><CitationCard v-for="(citation, index) in message.answer.citations" :key="citation.chunk_id" :citation="citation" :chunks="message.answer.retrieved_chunks" :index="index" /></div></details>
              <details v-if="message.answer.agent_steps.length" class="message-evidence"><summary>查看 Agent 处理轨迹</summary><AgentTrace :steps="message.answer.agent_steps" /></details>
            </template>
          </div>
        </article>
        <article v-if="loading" class="chat-message assistant"><div class="message-avatar">M</div><div class="typing"><i /><i /><i /><span>正在理解上下文并检索证据…</span></div></article>
      </div>
      <footer class="chat-composer">
        <textarea v-model="draft" rows="2" maxlength="2000" placeholder="输入问题…（Enter 发送，Shift+Enter 换行）" :disabled="loading" @keydown="onKeydown" />
        <div class="composer-footer"><span>DeepSeek · LangGraph · 自动检索路由</span><button type="button" :disabled="loading || draft.trim().length < 2" aria-label="发送" @click="send"><el-icon><Promotion /></el-icon></button></div>
      </footer>
    </section>
  </div>
</template>
