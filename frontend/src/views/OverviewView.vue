<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, DataAnalysis, DocumentChecked, Lock, Search } from '@element-plus/icons-vue'
import { medopsApi } from '@/api/medops'
import StatCard from '@/components/StatCard.vue'
import { useAppStore } from '@/stores/app'

const app = useAppStore()
const router = useRouter()
const documentCount = ref<number | null>(null)
const counting = ref(false)

const requests = computed(() => app.metrics?.requests)

async function loadDocumentCount() {
  if (!app.knowledgeBases.length || counting.value) return
  counting.value = true
  try {
    const pages = await Promise.all(app.knowledgeBases.map((kb) => medopsApi.listDocuments(kb.id, { limit: 1, offset: 0, query: '' })))
    documentCount.value = pages.reduce((sum, page) => sum + page.total, 0)
  } finally {
    counting.value = false
  }
}

watch(() => app.knowledgeBases.length, loadDocumentCount)
onMounted(loadDocumentCount)
</script>

<template>
  <div class="page-stack">
    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">MEDOPS MEDICAL KNOWLEDGE AGENT</p>
        <h2>让企业知识回答，<br><em>每一句都有出处。</em></h2>
        <p class="hero-description">统一接入医学资料、医疗器械文档与内部知识。系统自动选择合适的处理路径，用户只需要描述问题。</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" @click="router.push('/answer')">开始提问 <el-icon><ArrowRight /></el-icon></el-button>
          <el-button size="large" @click="router.push('/documents')">管理知识</el-button>
        </div>
      </div>
      <div class="signal-visual" aria-hidden="true">
        <div class="orbit one" /><div class="orbit two" />
        <div class="signal-core"><span>RAG</span><small>GROUNDED</small></div>
        <span class="signal-node n1"><el-icon><Search /></el-icon> 检索</span>
        <span class="signal-node n2"><el-icon><Lock /></el-icon> 安全</span>
        <span class="signal-node n3"><el-icon><DocumentChecked /></el-icon> 引用</span>
      </div>
    </section>

    <section class="stat-grid">
      <StatCard label="知识库" :value="app.knowledgeBases.length" caption="当前租户可见" />
      <StatCard label="知识文档" :value="documentCount ?? '—'" caption="可检索资料" />
      <StatCard label="24H 请求" :value="requests?.count ?? '—'" :caption="`${requests?.error_count ?? 0} 次错误`" />
      <StatCard label="服务版本" :value="app.health?.version ?? '—'" caption="企业知识 Agent" accent />
    </section>

    <section class="content-grid two">
      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">KNOWLEDGE SPACES</p><h3>当前知识空间</h3></div><el-button text type="primary" @click="router.push('/documents')">管理 <el-icon><ArrowRight /></el-icon></el-button></header>
        <el-skeleton v-if="app.connecting" :rows="3" animated />
        <div v-else-if="app.knowledgeBases.length" class="space-list">
          <button v-for="kb in app.knowledgeBases.slice(0, 5)" :key="kb.id" type="button" @click="app.activeKbId = kb.id; router.push('/documents')">
            <span class="space-icon"><el-icon><DataAnalysis /></el-icon></span>
            <span><b>{{ kb.name }}</b><small>{{ kb.description || '未填写说明' }}</small></span>
            <i>KB-{{ String(kb.id).padStart(2, '0') }}</i>
          </button>
        </div>
        <el-empty v-else description="当前租户还没有知识库" :image-size="72" />
      </article>

      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">SAFE PIPELINE</p><h3>自动处理链路</h3></div></header>
        <ol class="pipeline-list">
          <li><b>01</b><span><strong>身份与权限边界</strong><small>请求进入前完成租户隔离</small></span><i>BOUND</i></li>
          <li><b>02</b><span><strong>问题理解与自动路由</strong><small>无需用户配置技术参数</small></span><i>AUTO</i></li>
          <li><b>03</b><span><strong>证据检索与排序</strong><small>仅使用当前知识空间</small></span><i>RANKED</i></li>
          <li><b>04</b><span><strong>回答核验与引用</strong><small>证据不足时明确拒答</small></span><i>CITED</i></li>
        </ol>
      </article>
    </section>
  </div>
</template>
