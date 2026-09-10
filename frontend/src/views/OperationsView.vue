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
const compareLoading = ref(false)
const answerLoading = ref(false)
const searchResult = ref<SearchResponse | null>(null)
const comparisonResults = ref<Array<{
  requested: RetrievalStrategy
  executed: RetrievalStrategy | 'failed'
  retrieval_ms: number | null
  hits: number
  top_source: string
  top_score: number | null
  reason: string
}>>([])
const answerResult = ref<AnswerResponse | null>(null)
let searchController: AbortController | null = null
let answerController: AbortController | null = null

const request = computed(() => app.metrics?.requests)
const queues = computed(() => Object.entries(app.metrics?.queues ?? {}))
const stages = computed(() => Object.entries(app.metrics?.pipeline_stages ?? {}))
const routingStrategies = computed(() => Object.entries(app.metrics?.rag_routing.strategies ?? {}))
const routingReasons = computed(() => Object.entries(app.metrics?.rag_routing.reasons ?? {}))
const providerRejections = computed(() =>
  (app.metrics?.rag_routing.overload_rejections ?? 0)
  + (app.metrics?.rag_routing.circuit_rejections ?? 0)
  + (app.metrics?.rag_routing.deadline_rejections ?? 0),
)
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

async function runComparison() {
  const knowledgeBaseId = validateLab()
  if (!knowledgeBaseId) return
  searchController?.abort()
  searchController = new AbortController()
  compareLoading.value = true
  comparisonResults.value = []
  const compared: RetrievalStrategy[] = ['auto', 'bm25', 'rrf', 'parent_child']
  try {
    comparisonResults.value = await Promise.all(compared.map(async (strategy) => {
      try {
        const result = await medopsApi.search({
          query: lab.question.trim(),
          knowledge_base_id: knowledgeBaseId,
          top_k: lab.top_k,
          strategy,
          query_transform: lab.query_transform,
        }, searchController?.signal)
        return {
          requested: strategy,
          executed: result.strategy,
          retrieval_ms: result.retrieval_ms,
          hits: result.results.length,
          top_source: result.results[0]?.source ?? '—',
          top_score: result.results[0]?.score ?? null,
          reason: result.routing?.reason_code ?? 'fixed_admin_strategy',
        }
      } catch (error) {
        if ((error as Error).name === 'AbortError') throw error
        return {
          requested: strategy,
          executed: 'failed' as const,
          retrieval_ms: null,
          hits: 0,
          top_source: '—',
          top_score: null,
          reason: error instanceof Error ? error.message : '未知错误',
        }
      }
    }))
    const completed = comparisonResults.value.filter((item) => item.executed !== 'failed').length
    app.log('管理员引擎对比', `${completed}/${compared.length} completed`)
  } catch (error) {
    if ((error as Error).name !== 'AbortError') ElMessage.error(`引擎对比失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    compareLoading.value = false
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
    query_transform: lab.query_transform,
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

    <section class="stat-grid ops-stat-grid">
      <StatCard label="请求总量" :value="request?.count ?? '—'" caption="最近 24 小时" />
      <StatCard label="P95 延迟" :value="request ? `${request.latency_ms.p95.toLocaleString()} ms` : '—'" caption="端到端请求" />
      <StatCard label="安全拒答" :value="request?.abstained_count ?? '—'" caption="证据或边界门禁" />
      <StatCard label="Fallback" :value="request?.fallback_count ?? '—'" caption="模型服务降级" accent />
      <StatCard label="Provider 拒绝" :value="app.metrics ? providerRejections : '—'" caption="过载、熔断或截止，均显式返回" />
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
          <el-button :loading="compareLoading" @click="runComparison"><el-icon><DataAnalysis /></el-icon>对比核心文本引擎</el-button>
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

      <div v-if="comparisonResults.length" class="lab-result">
        <div class="section-title"><span>同问题并排对比</span><small>Auto / BM25 / RRF / Parent-Child · 相同 Top K 与 Query Transform</small></div>
        <el-table :data="comparisonResults" table-layout="fixed">
          <el-table-column prop="requested" label="请求策略" width="125" />
          <el-table-column prop="executed" label="实际策略" width="125" />
          <el-table-column label="延迟" width="110"><template #default="{ row }">{{ row.retrieval_ms === null ? '—' : `${row.retrieval_ms.toFixed(1)} ms` }}</template></el-table-column>
          <el-table-column prop="hits" label="Hits" width="75" />
          <el-table-column prop="top_source" label="Top-1 来源" min-width="180" show-overflow-tooltip />
          <el-table-column label="Top-1 Score" width="115"><template #default="{ row }">{{ row.top_score === null ? '—' : Number(row.top_score).toFixed(3) }}</template></el-table-column>
          <el-table-column prop="reason" label="路由/错误原因" min-width="210" show-overflow-tooltip />
        </el-table>
      </div>

      <div v-if="answerResult" class="lab-result">
        <div class="section-title"><span>完整链路结果</span><small>{{ answerResult.orchestration }} · {{ answerResult.provider }} · {{ answerResult.query_transform }} transform · {{ answerResult.token_usage }} tokens</small></div>
        <el-alert :title="answerResult.abstained ? `已拒答：${answerResult.reason}` : answerResult.answer" :type="answerResult.abstained ? 'warning' : 'success'" :closable="false" show-icon />
      </div>
    </section>

    <section class="content-grid two ops-grid">
      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">ADAPTIVE ROUTING · 24 HOURS</p><h3>检索策略分布</h3></div><span>{{ app.metrics?.rag_routing.event_count ?? 0 }} events</span></header>
        <div v-if="routingStrategies.length" class="queue-list">
          <div v-for="([name, count]) in routingStrategies" :key="name" class="queue-row"><span><b>{{ name }}</b><small>服务端最终执行策略</small></span><el-tag effect="plain">{{ count }}</el-tag></div>
        </div>
        <el-empty v-else description="暂无自适应路由样本" :image-size="70" />
      </article>
      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">ROUTING REASONS · 24 HOURS</p><h3>路由原因分布</h3></div><span>仅管理员可见</span></header>
        <div v-if="routingReasons.length" class="queue-list">
          <div v-for="([name, count]) in routingReasons" :key="name" class="queue-row"><span><b>{{ name }}</b><small>可审计 reason code</small></span><el-tag type="info" effect="plain">{{ count }}</el-tag></div>
        </div>
        <el-empty v-else description="暂无原因统计" :image-size="70" />
      </article>
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
        <header class="panel-header"><div><p class="eyebrow">PROVIDER RUNTIME · PROCESS LOCAL</p><h3>模型容量与熔断</h3></div><el-tag :type="app.metrics?.provider_runtime.circuit.state === 'closed' ? 'success' : 'danger'" effect="light">{{ app.metrics?.provider_runtime.circuit.state ?? 'unknown' }}</el-tag></header>
        <div v-if="app.metrics" class="queue-list">
          <div class="queue-row"><span><b>活动调用</b><small>当前进程实际 HTTP attempt</small></span><el-tag effect="plain">{{ app.metrics.provider_runtime.capacity.active }} / {{ app.metrics.provider_runtime.capacity.max_concurrency }}</el-tag></div>
          <div class="queue-row"><span><b>排队请求</b><small>全局上限 {{ app.metrics.provider_runtime.capacity.max_queue_waiters }}</small></span><el-tag effect="plain">{{ app.metrics.provider_runtime.capacity.waiting }}</el-tag></div>
          <div class="queue-row"><span><b>租户公平上限</b><small>每租户活动 / 等待</small></span><el-tag effect="plain">{{ app.metrics.provider_runtime.capacity.max_concurrency_per_tenant }} / {{ app.metrics.provider_runtime.capacity.max_queue_waiters_per_tenant }}</el-tag></div>
          <div class="queue-row"><span><b>端到端截止</b><small>排队、HTTP 与退避共享</small></span><el-tag effect="plain">{{ app.metrics.provider_runtime.policy.request_deadline_seconds }} s</el-tag></div>
          <div class="queue-row"><span><b>全局重试预算</b><small>已消费 {{ app.metrics.provider_runtime.retry_budget.retries_consumed }} · 拒绝 {{ app.metrics.provider_runtime.retry_budget.global.rejected }}</small></span><el-tag effect="plain">{{ app.metrics.provider_runtime.retry_budget.global.remaining }} / {{ app.metrics.provider_runtime.retry_budget.global.capacity }}</el-tag></div>
          <div class="queue-row"><span><b>租户重试预算</b><small>{{ app.metrics.provider_runtime.retry_budget.per_tenant.tracked }} 个活跃租户 · 拒绝 {{ app.metrics.provider_runtime.retry_budget.per_tenant.rejected }}</small></span><el-tag effect="plain">{{ app.metrics.provider_runtime.retry_budget.per_tenant.remaining_min ?? '—' }} / {{ app.metrics.provider_runtime.retry_budget.per_tenant.capacity }}</el-tag></div>
          <div class="queue-row"><span><b>连续故障</b><small>breaker epoch {{ app.metrics.provider_runtime.circuit.epoch }}</small></span><el-tag :type="app.metrics.provider_runtime.circuit.consecutive_failures ? 'warning' : 'success'" effect="plain">{{ app.metrics.provider_runtime.circuit.consecutive_failures }}</el-tag></div>
        </div>
        <el-empty v-else description="暂无 Provider 运行数据" :image-size="70" />
      </article>
    </section>

    <section class="surface-panel">
      <header class="panel-header"><div><p class="eyebrow">CURRENT SESSION</p><h3>本次会话</h3></div><el-icon class="panel-icon"><DataAnalysis /></el-icon></header>
      <div v-if="app.activity.length" class="activity-list">
        <div v-for="(item, index) in app.activity" :key="`${item.time}-${index}`"><i /><span><b>{{ item.action }}</b><small>{{ item.outcome }}</small></span><time>{{ item.time }}</time></div>
      </div>
      <el-empty v-else description="尚无操作记录" :image-size="70" />
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
