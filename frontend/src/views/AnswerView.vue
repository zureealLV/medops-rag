<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { ChatLineRound, CircleCheck, Document, Promotion, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { medopsApi } from '@/api/medops'
import AgentTrace from '@/components/AgentTrace.vue'
import CitationCard from '@/components/CitationCard.vue'
import { useAppStore } from '@/stores/app'
import type { AnswerResponse } from '@/types/api'

const app = useAppStore()
const question = ref('哪些因素可能影响脉搏血氧仪读数？')
const selectedKbId = computed({
  get: () => app.activeKbId,
  set: (value) => { app.activeKbId = value },
})
const loading = ref(false)
const answer = ref<AnswerResponse | null>(null)
let controller: AbortController | null = null

const totalDuration = computed(() => Number((answer.value ? answer.value.retrieval_ms + answer.value.model_ms : 0).toFixed(1)))
const routeLabel = computed(() => {
  const route = answer.value?.retrieval_routing
  if (!route) return ''
  const names = { bm25: 'BM25 精确检索', rrf: 'RRF 混合检索', parent_child: '父子分片检索' }
  return `${names[route.strategy]} · 置信度 ${(route.confidence * 100).toFixed(0)}%`
})

async function submit() {
  const content = question.value.trim()
  if (content.length < 2) return ElMessage.warning('问题至少需要 2 个字符')
  if (!selectedKbId.value) return ElMessage.warning('请先选择知识库')
  controller?.abort()
  controller = new AbortController()
  loading.value = true
  answer.value = null
  try {
    answer.value = await medopsApi.answer({ question: content, knowledge_base_id: selectedKbId.value, top_k: 5 }, controller.signal)
    app.log('证据问答', answer.value.abstained ? 'ABSTAINED' : 'CITED')
  } catch (error) {
    if ((error as Error).name !== 'AbortError') ElMessage.error(`回答失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    loading.value = false
  }
}

function keyboardSubmit(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') void submit()
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="answer-layout">
    <section class="surface-panel query-card">
      <header class="panel-header">
        <div><p class="eyebrow">GROUNDED ANSWER</p><h3>向知识库提问</h3></div>
        <kbd>Ctrl ↵</kbd>
      </header>

      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="知识空间">
          <el-select v-model="selectedKbId" placeholder="选择一个知识库" style="width: 100%">
            <el-option v-for="kb in app.knowledgeBases" :key="kb.id" :label="kb.name" :value="kb.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="你的问题">
          <el-input v-model="question" type="textarea" :rows="8" maxlength="2000" show-word-limit resize="vertical" @keydown="keyboardSubmit" />
        </el-form-item>
        <el-button type="primary" size="large" class="full-button" :loading="loading" @click="submit">
          <el-icon v-if="!loading"><Promotion /></el-icon>{{ loading ? '正在检索与核验…' : '生成带引用回答' }}
        </el-button>
      </el-form>
      <div class="auto-note"><el-icon><CircleCheck /></el-icon><span><b>已启用自动处理</b><small>系统会根据问题与语料自动选择检索、证据和编排路径。</small></span></div>
      <p class="query-hint">边界测试：“明天合肥会不会下雨？” 系统应明确拒答。</p>
    </section>

    <section v-loading="loading" class="surface-panel answer-card">
      <div v-if="loading" class="answer-empty"><div class="pulse-glyph"><ChatLineRound /></div><h3>正在查找可信证据</h3><p>系统正在理解问题、检索知识并核验引用。</p></div>
      <div v-else-if="!answer" class="answer-empty"><div class="empty-glyph"><ChatLineRound /></div><h3>等待问题</h3><p>回答、引用来源和处理轨迹将在这里出现。</p></div>
      <template v-else>
        <header class="answer-status">
          <el-tag :type="answer.abstained ? 'warning' : 'success'" effect="light" size="large">
            <el-icon><component :is="answer.abstained ? Warning : CircleCheck" /></el-icon>
            {{ answer.abstained ? '证据不足，已安全拒答' : '已依据可信来源回答' }}
          </el-tag>
          <span>{{ totalDuration }} ms</span>
        </header>
        <div class="answer-copy">{{ answer.answer }}</div>
        <el-alert v-if="answer.reason" :title="answer.reason" type="warning" show-icon :closable="false" />

        <div class="telemetry-grid">
          <div><span>检索</span><b>{{ Number(answer.retrieval_ms).toFixed(1) }} ms</b></div>
          <div><span>生成</span><b>{{ Number(answer.model_ms).toFixed(1) }} ms</b></div>
          <div><span>Token</span><b>{{ answer.token_usage.toLocaleString() }}</b></div>
          <div><span>缓存输入</span><b>{{ answer.cached_prompt_tokens.toLocaleString() }}</b></div>
        </div>

        <el-alert
          v-if="answer.retrieval_routing"
          :title="`自动路由：${routeLabel}`"
          :description="`原因代码：${answer.retrieval_routing.reason_code}`"
          type="info"
          show-icon
          :closable="false"
        />

        <AgentTrace v-if="answer.agent_steps.length" :steps="answer.agent_steps" />

        <section class="evidence-section">
          <div class="section-title"><span>引用来源</span><small>{{ answer.citations.length + answer.visual_citations.length }} 条证据</small></div>
          <div v-if="answer.citations.length" class="citation-grid">
            <CitationCard v-for="(item, index) in answer.citations" :key="`${item.document_id}-${item.chunk_id}`" :citation="item" :chunks="answer.retrieved_chunks" :index="index" />
          </div>
          <div v-for="(item, index) in answer.visual_citations" :key="item.artifact_id" class="visual-reference">
            <el-icon><Document /></el-icon><span><b>[图像{{ index + 1 }}] {{ item.source }}</b><small>{{ item.page_number ? `第 ${item.page_number} 页` : '原始视觉证据' }}</small></span>
          </div>
          <el-empty v-if="!answer.citations.length && !answer.visual_citations.length" description="没有可展示的证据" :image-size="60" />
        </section>
      </template>
    </section>
  </div>
</template>
