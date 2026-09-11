<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ChatDotRound,
  Collection,
  Connection,
  DataBoard,
  Files,
  Fold,
  Operation,
  Setting,
  User,
  WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ConnectionDialog from './ConnectionDialog.vue'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const settingsVisible = ref(false)
const mobileNav = ref(false)

const baseNavItems = [
  { path: '/overview', label: '数据看板', caption: 'Overview', icon: DataBoard },
  { path: '/documents', label: '知识库管理', caption: 'Knowledge', icon: Collection },
  { path: '/answer', label: '智能问答', caption: 'Evidence QA', icon: ChatDotRound },
  { path: '/operations', label: '运行控制台', caption: 'Operations', icon: Operation },
  { path: '/mcp', label: 'MCP 服务', caption: 'Tool Gateway', icon: Connection },
  { path: '/settings', label: 'API 配置', caption: 'Provider', icon: Setting },
]
const navItems = computed(() => baseNavItems.filter((item) => (
  !['/operations', '/settings'].includes(item.path) || app.identity?.role === 'admin'
)))

const pageTitle = computed(() => String(route.meta.title ?? '系统总览'))

watch(
  [() => app.identity?.role, () => route.path],
  ([role, path]) => {
    if (role && role !== 'admin' && ['/operations', '/settings'].includes(path)) void router.replace('/overview')
  },
  { immediate: true },
)

async function reconnect() {
  try {
    await app.connect()
  } catch (error) {
    ElMessage.error(`连接失败：${error instanceof Error ? error.message : '未知错误'}`)
  }
}

function navigate(path: string) {
  void router.push(path)
  mobileNav.value = false
}

onMounted(reconnect)
</script>

<template>
  <div class="app-shell">
    <header class="app-topbar">
      <button class="brand" type="button" aria-label="返回数据看板" @click="navigate('/overview')">
        <span class="brand-mark"><i /><i /><i /></span>
        <span><strong>MEDOPS RAG</strong><small>MEDICAL KNOWLEDGE OS</small></span>
      </button>

      <nav :class="['nav-menu', { open: mobileNav }]" aria-label="主导航">
        <button
          v-for="item in navItems"
          :key="item.path"
          type="button"
          :class="['nav-item', { active: route.path === item.path }]"
          @click="navigate(item.path)"
        >
          <el-icon><component :is="item.icon" /></el-icon>
          <span><b>{{ item.label }}</b><small>{{ item.caption }}</small></span>
        </button>
        <a class="mobile-api-link" href="/docs" target="_blank" rel="noreferrer">API 文档 ↗</a>
      </nav>

      <div class="top-actions">
        <button class="identity-chip" type="button" @click="settingsVisible = true">
          <el-icon><User /></el-icon>
          <span><b>{{ app.identity?.actor ?? '未连接' }}</b><small>{{ app.identity?.tenant_id ?? '等待身份' }}</small></span>
        </button>
        <button :class="['health-pill', { online: app.online, offline: app.connectionError }]" type="button" @click="reconnect">
          <i />{{ app.connecting ? '连接中' : app.online ? '服务正常' : '连接异常' }}
        </button>
        <el-button class="settings-button" circle aria-label="API 配置" @click="navigate('/settings')"><el-icon><Setting /></el-icon></el-button>
        <button class="mobile-menu" type="button" aria-label="打开导航" @click="mobileNav = true">
          <el-icon><Fold /></el-icon>
        </button>
      </div>
    </header>

    <div v-if="mobileNav" class="nav-mask" @click="mobileNav = false" />

    <main class="main-area">
      <section class="context-bar">
        <div class="page-heading">
          <p>TENANT-SCOPED · AUDITABLE · SAFE BY DEFAULT</p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="context-actions">
          <span class="safety-note"><el-icon><WarningFilled /></el-icon> 医学教育与器械知识，不替代专业诊疗</span>
          <a class="api-link" href="/docs" target="_blank" rel="noreferrer"><el-icon><Files /></el-icon> API 文档 ↗</a>
        </div>
      </section>

      <div class="view-container">
        <RouterView />
      </div>
    </main>

    <ConnectionDialog v-model="settingsVisible" @connected="reconnect" />
  </div>
</template>
