<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { DataAnalysis, Promotion, Refresh, Search, Timer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { medopsApi } from '@/api/medops'
import StatCard from '@/components/StatCard.vue'
import { useAppStore } from '@/stores/app'
import type {
  AdminAnswerRequest,
  AnswerResponse,
  OrchestrationEngine,
  QueryTransform,
  RetrievalProfile,
  RetrievalStrategy,
  SearchResponse,
  VisualStrategy,
} from '@/types/api'

const app = useAppStore()
const refreshing = ref(false)
const searchLoading = ref(false)
const answerLoading = ref(false)
const searchResult = ref<SearchResponse | null>(null)
const answerResult = ref<AnswerResponse | null>(null)
let searchController: AbortController | null = null
let answerController: AbortController | null = null

const request = computed(() => app.metrics?.requests)
const queues = computed(() => Object.entries(app.metrics?.queues ?? {}))
const stages = computed(() => Object.entries(app.metrics?.pipeline_stages ?? {}))
const isAdmin = computed(() => app.identity?.role === 'admin')
const selectedKbId = computed({
  get: () => app.activeKbId,
  set: (value: number | null) => { app.activeKbId = value },
})

const lab = reactive<{
  question: string
  top_k: number
  strategy: RetrievalStrategy
  query_transform: QueryTransform
  retrieval_profile: RetrievalProfile
  visual_strategy: VisualStrategy
  orchestration: OrchestrationEngine
}>({
  question: 'LIS 接口超时先检查什么？',
  top_k: 5,
  strategy: 'auto',
  query_transform: 'auto',
  retrieval_profile: 'auto',
  visual_strategy: 'fusion',
  orchestration: 'langgraph',
})

const strategies: RetrievalStrategy[] = ['auto', 'bm25', 'rrf', 'parent_child', 'keyword', 'vector', 'weighted']
const transforms: QueryTransform[] = ['auto', 'none', 'rewrite', 'multi_query', 'hyde']
const profiles: RetrievalProfile[] = ['auto', 'text', 'visual']
const visualStrategies: VisualStrategy[] = ['fusion', 'ocr', 'image']
const orchestrators: OrchestrationEngine[] = ['langgraph', 'langchain', 'classic']

async function refresh() {
  refreshing.value = true
  try {
    await app.loadMetrics()
    app.log('刷新运行指标')
  } catch (error) {
    ElMessage.error(`指标读取失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    refreshing.value = false
  }
}

function validateLab(): number | null {
  if (!isAdmin.value) {
    ElMessage.error('只有管理员可以运行策略实验')
    return null
  }
  if (!selectedKbId.value) {
    ElMessage.warning('请先选择知识库')
    return null
  }
  if (lab.question.trim().length < 2) {
    ElMessage.warning('问题至少需要 2 个字符')
    return null
  }
  return selectedKbId.value
}

async function runSearch() {
  const knowledgeBaseId = validateLab()
  if (!knowledgeBaseId) return
  searchController?.abort()
  searchController = new AbortController()
  searchLoading.value = true
  searchResult.value = null
  try {
    searchResult.value = await medopsApi.search({
      query: lab.question.trim(),
      knowledge_base_id: knowledgeBaseId,
      top_k: lab.top_k,
      strategy: lab.strategy,
      query_transform: lab.query_transform,
    }, searchController.signal)
    app.log('管理员检索实验', `${searchResult.value.strategy} · ${searchResult.value.results.length} hits`)
  } catch (error) {
    if ((error as Error).name !== 'AbortError') ElMessage.error(`检索实验失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    searchLoading.value = false
  }
}

async function runAnswer() {
  const knowledgeBaseId = validateLab()
  if (!knowledgeBaseId) return
  answerController?.abort()
  answerController = new AbortController()
  answerLoading.value = true
  answerResult.value = null
  const payload: AdminAnswerRequest = {
    question: lab.question.trim(),
    knowledge_base_id: knowledgeBaseId,
    top_k: lab.top_k,
    retrieval_profile: lab.retrieval_profile,
    text_strategy: lab.strategy,
    visual_strategy: lab.visual_strategy,
    orchestration: lab.orchestration,
  }
  try {
    answerResult.value = await medopsApi.adminAnswer(payload, answerController.signal)
    app.log('管理员完整链路实验', `${answerResult.value.orchestration} · ${answerResult.value.provider}`)
  } catch (error) {
    if ((error as Error).name !== 'AbortError') ElMessage.error(`完整链路实验失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    answerLoading.value = false
  }
}

onMounted(() => { if (isAdmin.value && !app.metrics) void refresh() })
onBeforeUnmount(() => { searchController?.abort(); answerController?.abort() })
</script>

<template>
  <div v-if="isAdmin" class="page-stack">
    <header class="section-heading">
      <div><p class="eyebrow">ADMIN CONTROL PLANE · 24 HOURS</p><h2>管理与运行控制台</h2><p>技术策略只在管理员侧用于基准、灰度与故障诊断；普通问答始终由系统自动路由。</p></div>
      <el-button size="large" :loading="refreshing" @click="refresh"><el-icon><Refresh /></el-icon>刷新指标</el-button>
    </header>

    <section class="stat-grid">
      <StatCard label="请求总量" :value="request?.count ?? '—'" caption="最近 24 小时" />
      <StatCard label="P95 延迟" :value="request ? `${request.latency_ms.p95.toLocaleString()} ms` : '—'" caption="端到端请求" />
      <StatCard label="安全拒答" :value="request?.abstained_count ?? '—'" caption="证据或边界门禁" />
      <StatCard label="Fallback" :value="request?.fallback_count ?? '—'" caption="模型服务降级" accent />
    </section>

    <section class="surface-panel admin-lab">
      <header class="panel-header">
        <div><p class="eyebrow">ADMIN-ONLY RETRIEVAL LAB</p><h3>检索与编排实验室</h3></div>
        <el-tag type="warning" effect="light">完整链路会消耗模型额度</el-tag>
      </header>
      <el-form label-position="top">
        <div class="admin-lab-grid">
          <el-form-item label="知识空间">
            <el-select v-model="selectedKbId" placeholder="选择知识库">
              <el-option v-for="kb in app.knowledgeBases" :key="kb.id" :label="kb.name" :value="kb.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="文本检索策略"><el-select v-model="lab.strategy"><el-option v-for="item in strategies" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="Query Transform"><el-select v-model="lab.query_transform"><el-option v-for="item in transforms" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="Top K"><el-input-number v-model="lab.top_k" :min="1" :max="10" /></el-form-item>
          <el-form-item label="证据类型"><el-select v-model="lab.retrieval_profile"><el-option v-for="item in profiles" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="视觉策略"><el-select v-model="lab.visual_strategy"><el-option v-for="item in visualStrategies" :key="item" :label="item" :value="item" /></el-select></el-form-item>
          <el-form-item label="编排引擎"><el-select v-model="lab.orchestration"><el-option v-for="item in orchestrators" :key="item" :label="item" :value="item" /></el-select></el-form-item>
        </div>
        <el-form-item label="实验问题"><el-input v-model="lab.question" type="textarea" :rows="3" maxlength="1000" show-word-limit /></el-form-item>
        <div class="lab-actions">
          <el-button type="primary" :loading="searchLoading" @click="runSearch"><el-icon><Search /></el-icon>仅运行检索</el-button>
          <el-button :loading="answerLoading" @click="runAnswer"><el-icon><Promotion /></el-icon>运行完整链路</el-button>
        </div>
      </el-form>

      <div v-if="searchResult" class="lab-result">
        <div class="section-title"><span>检索结果</span><small>{{ searchResult.strategy }} · {{ searchResult.retrieval_ms.toFixed(1) }} ms · {{ searchResult.results.length }} hits</small></div>
        <el-alert v-if="searchResult.routing" :title="`自动路由：${searchResult.routing.strategy}`" :description="searchResult.routing.reason_code" type="info" :closable="false" />
        <el-table :data="searchResult.results" max-height="320" table-layout="fixed" empty-text="没有达到证据阈值的结果">
          <el-table-column prop="source" label="来源" min-width="190" show-overflow-tooltip />
          <el-table-column prop="text" label="命中证据" min-width="360" show-overflow-tooltip />
          <el-table-column label="Score" width="100"><template #default="{ row }">{{ Number(row.score).toFixed(3) }}</template></el-table-column>
        </el-table>
      </div>

      <div v-if="answerResult" class="lab-result">
        <div class="section-title"><span>完整链路结果</span><small>{{ answerResult.orchestration }} · {{ answerResult.provider }} · {{ answerResult.token_usage }} tokens</small></div>
        <el-alert :title="answerResult.abstained ? `已拒答：${answerResult.reason}` : answerResult.answer" :type="answerResult.abstained ? 'warning' : 'success'" :closable="false" show-icon />
      </div>
    </section>

    <section class="content-grid two ops-grid">
      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">QUEUE STATE</p><h3>后台任务</h3></div><el-icon class="panel-icon"><Timer /></el-icon></header>
        <div v-if="queues.length" class="queue-list">
          <div v-for="([name, queue]) in queues" :key="name" class="queue-row">
            <span><b>{{ name === 'ingestion' ? '文档摄取' : name === 'summary' ? '内容摘要' : name }}</b><small>最早等待 {{ queue.oldest_queued_age_seconds.toFixed(1) }} 秒</small></span>
            <div><el-tag v-for="(count, state) in queue.states" :key="state" effect="plain">{{ state }} {{ count }}</el-tag><small v-if="!Object.keys(queue.states).length">暂无任务</small></div>
          </div>
        </div>
        <el-empty v-else description="暂无队列数据" :image-size="70" />
      </article>

      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">CURRENT SESSION</p><h3>本次会话</h3></div><el-icon class="panel-icon"><DataAnalysis /></el-icon></header>
        <div v-if="app.activity.length" class="activity-list">
          <div v-for="(item, index) in app.activity" :key="`${item.time}-${index}`"><i /><span><b>{{ item.action }}</b><small>{{ item.outcome }}</small></span><time>{{ item.time }}</time></div>
        </div>
        <el-empty v-else description="尚无操作记录" :image-size="70" />
      </article>
    </section>

    <section class="surface-panel stage-panel">
      <header class="panel-header"><div><p class="eyebrow">PIPELINE HEALTH</p><h3>处理阶段性能</h3></div><span>最近更新 {{ app.metrics ? new Date(app.metrics.generated_at).toLocaleString('zh-CN') : '—' }}</span></header>
      <el-table :data="stages.map(([name, data]) => ({ name, ...data }))" empty-text="暂无阶段数据" table-layout="fixed">
        <el-table-column prop="name" label="阶段" min-width="260" />
        <el-table-column prop="count" label="次数" width="100" />
        <el-table-column prop="avg_ms" label="平均时延 (ms)" width="160" />
        <el-table-column prop="p95_ms" label="P95 (ms)" width="140" />
        <el-table-column prop="error_count" label="错误" width="100"><template #default="{ row }"><el-tag :type="row.error_count ? 'danger' : 'success'" effect="light">{{ row.error_count }}</el-tag></template></el-table-column>
      </el-table>
    </section>
  </div>

  <el-result v-else icon="warning" title="正在验证管理员权限" sub-title="该页面只承载检索、证据和编排的管理端控制。" />
</template>
