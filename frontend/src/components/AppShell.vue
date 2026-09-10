<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { DataAnalysis, Document, Files, Fold, House, Setting, User, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import ConnectionDialog from './ConnectionDialog.vue'
import { useAppStore } from '@/stores/app'

const route = useRoute()
const router = useRouter()
const app = useAppStore()
const settingsVisible = ref(false)
const mobileNav = ref(false)

const baseNavItems = [
  { path: '/overview', label: '总览', caption: 'Overview', icon: House },
  { path: '/answer', label: '证据问答', caption: 'Evidence QA', icon: DataAnalysis },
  { path: '/documents', label: '知识文档', caption: 'Documents', icon: Files },
  { path: '/operations', label: '运行状态', caption: 'Operations', icon: Document },
]
const navItems = computed(() => baseNavItems.filter((item) => (
  item.path !== '/operations' || app.identity?.role === 'admin'
)))

const pageTitle = computed(() => String(route.meta.title ?? '系统总览'))

watch(
  [() => app.identity?.role, () => route.path],
  ([role, path]) => {
    if (role && role !== 'admin' && path === '/operations') void router.replace('/overview')
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
    <aside class="sidebar" :class="{ open: mobileNav }">
      <button class="brand" type="button" aria-label="返回总览" @click="navigate('/overview')">
        <span class="brand-mark"><i /><i /><i /></span>
        <span><strong>MEDOPS</strong><small>ENTERPRISE RAG</small></span>
      </button>

      <nav class="nav-menu" aria-label="主导航">
        <button
          v-for="(item, index) in navItems"
          :key="item.path"
          type="button"
          :class="['nav-item', { active: route.path === item.path }]"
          @click="navigate(item.path)"
        >
          <span class="nav-number">0{{ index + 1 }}</span>
          <el-icon><component :is="item.icon" /></el-icon>
          <span class="nav-copy"><b>{{ item.label }}</b><small>{{ item.caption }}</small></span>
        </button>
      </nav>

      <div class="sidebar-spacer" />
      <div class="safety-note">
        <el-icon><WarningFilled /></el-icon>
        <div><b>知识边界</b><p>面向医学教育与器械知识，不替代专业诊疗。</p></div>
      </div>
      <a class="api-link" href="/docs" target="_blank" rel="noreferrer">API 文档 <span>↗</span></a>
    </aside>

    <div v-if="mobileNav" class="nav-mask" @click="mobileNav = false" />

    <main class="main-area">
      <header class="topbar">
        <button class="mobile-menu" type="button" aria-label="打开导航" @click="mobileNav = true">
          <el-icon><Fold /></el-icon>
        </button>
        <div class="page-heading">
          <p>TENANT-SCOPED · AUDITABLE · SAFE BY DEFAULT</p>
          <h1>{{ pageTitle }}</h1>
        </div>
        <div class="top-actions">
          <div :class="['identity-chip', { muted: !app.identity }]">
            <el-icon><User /></el-icon>
            <span><b>{{ app.identity?.actor ?? '未连接' }}</b><small>{{ app.identity?.tenant_id ?? '等待身份' }}</small></span>
          </div>
          <button :class="['health-pill', { online: app.online, offline: app.connectionError }]" type="button" @click="reconnect">
            <i />{{ app.connecting ? '正在连接' : app.online ? '服务正常' : '连接异常' }}
          </button>
          <el-button circle aria-label="连接设置" @click="settingsVisible = true"><el-icon><Setting /></el-icon></el-button>
        </div>
      </header>

      <div class="view-container">
        <RouterView />
      </div>
    </main>

    <ConnectionDialog v-model="settingsVisible" @connected="reconnect" />
  </div>
</template>
