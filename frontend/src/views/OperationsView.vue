<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Refresh, Timer } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import StatCard from '@/components/StatCard.vue'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const refreshing = ref(false)
const request = computed(() => app.metrics?.requests)
const queues = computed(() => Object.entries(app.metrics?.queues ?? {}))
const stages = computed(() => Object.entries(app.metrics?.pipeline_stages ?? {}))

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

onMounted(() => { if (!app.metrics) void refresh() })
</script>

<template>
  <div class="page-stack">
    <header class="section-heading">
      <div><p class="eyebrow">OBSERVABILITY · 24 HOURS</p><h2>运行状态</h2><p>查看当前租户的请求、时延和后台任务，不展示面向管理员的策略配置。</p></div>
      <el-button size="large" :loading="refreshing" @click="refresh"><el-icon><Refresh /></el-icon>刷新指标</el-button>
    </header>

    <section class="stat-grid">
      <StatCard label="请求总量" :value="request?.count ?? '—'" caption="最近 24 小时" />
      <StatCard label="P95 延迟" :value="request ? `${request.latency_ms.p95.toLocaleString()} ms` : '—'" caption="端到端请求" />
      <StatCard label="安全拒答" :value="request?.abstained_count ?? '—'" caption="证据或边界门禁" />
      <StatCard label="Fallback" :value="request?.fallback_count ?? '—'" caption="模型服务降级" accent />
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
        <header class="panel-header"><div><p class="eyebrow">CURRENT SESSION</p><h3>本次会话</h3></div></header>
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
        <el-table-column prop="error_count" label="错误" width="100">
          <template #default="{ row }"><el-tag :type="row.error_count ? 'danger' : 'success'" effect="light">{{ row.error_count }}</el-tag></template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>
