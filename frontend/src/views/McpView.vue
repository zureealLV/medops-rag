<script setup lang="ts">
import { computed, ref } from 'vue'
import { Check, Connection, CopyDocument, Promotion, Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { medopsApi } from '@/api/medops'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const testing = ref(false)
const protocol = ref('—')
const serverVersion = ref('—')
const discoveredTools = ref<Array<{ name: string; description: string }>>([])
const endpoint = computed(() => `${window.location.origin}/mcp/`)

const clientConfig = computed(() => JSON.stringify({
  mcpServers: {
    medops: {
      type: 'http',
      url: endpoint.value,
      headers: auth.profile.authMode === 'api_key'
        ? { Authorization: 'Bearer <MEDOPS_API_KEY>' }
        : {
            'X-Tenant-ID': auth.profile.tenantId,
            'X-Actor-ID': auth.profile.actorId,
          },
    },
  },
}, null, 2))

const fallbackTools = [
  { name: 'list_knowledge_bases', description: '列出当前认证租户可见的知识库。' },
  { name: 'rag_search', description: '仅检索证据，不生成答案，返回排序、来源和页码。' },
  { name: 'rag_answer', description: '执行安全策略、自动路由、生成回答并保留引用与 Agent 轨迹。' },
]
const visibleTools = computed(() => discoveredTools.value.length ? discoveredTools.value : fallbackTools)

async function copy(text: string) {
  await navigator.clipboard.writeText(text)
  ElMessage.success('已复制')
}

async function testConnection() {
  testing.value = true
  try {
    const [initialized, tools] = await Promise.all([
      medopsApi.mcpInitialize(),
      medopsApi.mcpListTools(),
    ])
    protocol.value = initialized.result.protocolVersion
    serverVersion.value = initialized.result.serverInfo.version
    discoveredTools.value = tools.result.tools.map(({ name, description }) => ({ name, description }))
    ElMessage.success(`MCP 连接正常，发现 ${discoveredTools.value.length} 个工具`)
  } catch (error) {
    ElMessage.error(`MCP 测试失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    testing.value = false
  }
}
</script>

<template>
  <div class="page-stack mcp-page">
    <section class="mcp-hero surface-panel">
      <div>
        <p class="eyebrow">MODEL CONTEXT PROTOCOL · STREAMABLE HTTP</p>
        <h2>让外部 AI 安全调用<br><em>MedOps 证据能力。</em></h2>
        <p>不是把旧 SSE 壳子搬过来，而是用官方 MCP SDK 暴露租户隔离、纯检索与可审计回答。</p>
        <div class="hero-actions">
          <el-button type="primary" size="large" :loading="testing" @click="testConnection">
            <el-icon><Connection /></el-icon> 测试 MCP 连接
          </el-button>
          <el-button size="large" @click="copy(endpoint)"><el-icon><CopyDocument /></el-icon> 复制地址</el-button>
        </div>
      </div>
      <div class="mcp-signal" aria-hidden="true">
        <span class="mcp-port p1">AI</span><span class="mcp-port p2">RAG</span><span class="mcp-port p3">KB</span>
        <div><el-icon><Promotion /></el-icon><b>MCP</b><small>CONNECTED TO EVIDENCE</small></div>
      </div>
    </section>

    <section class="mcp-grid">
      <article class="surface-panel connection-card">
        <header class="panel-header"><div><p class="eyebrow">CONNECTION</p><h3>服务连接信息</h3></div><el-tag type="success" effect="light" round>已启用</el-tag></header>
        <dl class="connection-list">
          <div><dt>Endpoint</dt><dd><code>{{ endpoint }}</code><el-button text type="primary" @click="copy(endpoint)">复制</el-button></dd></div>
          <div><dt>Transport</dt><dd>Streamable HTTP</dd></div>
          <div><dt>Protocol</dt><dd>{{ protocol }}</dd></div>
          <div><dt>Server</dt><dd>MedOps RAG {{ serverVersion }}</dd></div>
          <div><dt>Identity</dt><dd>{{ auth.profile.authMode === 'api_key' ? 'Bearer API Key' : `${auth.profile.tenantId} / ${auth.profile.actorId}` }}</dd></div>
        </dl>
      </article>

      <article class="surface-panel">
        <header class="panel-header"><div><p class="eyebrow">CLIENT CONFIG</p><h3>客户端配置</h3></div><el-button text type="primary" @click="copy(clientConfig)"><el-icon><CopyDocument /></el-icon> 复制</el-button></header>
        <pre class="config-code"><code>{{ clientConfig }}</code></pre>
        <p class="config-note">生产环境请使用 Bearer API Key；可信 Header 只适合受控的本地开发代理。</p>
      </article>
    </section>

    <section class="surface-panel">
      <header class="panel-header"><div><p class="eyebrow">DISCOVERABLE TOOLS</p><h3>可调用工具</h3></div><el-tag effect="plain">{{ visibleTools.length }} tools</el-tag></header>
      <div class="tool-grid">
        <article v-for="tool in visibleTools" :key="tool.name" class="tool-card">
          <span><el-icon><component :is="tool.name === 'rag_search' ? Search : tool.name === 'rag_answer' ? Promotion : Check" /></el-icon></span>
          <div><code>{{ tool.name }}</code><p>{{ tool.description }}</p></div>
        </article>
      </div>
    </section>
  </div>
</template>
