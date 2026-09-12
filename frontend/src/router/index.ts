import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue'), meta: { title: '登录', public: true } },
    { path: '/overview', name: 'overview', component: () => import('@/views/OverviewView.vue'), meta: { title: '系统总览' } },
    { path: '/answer', redirect: '/chat' },
    { path: '/chat', name: 'chat', component: () => import('@/views/ConversationView.vue'), meta: { title: '持续对话' } },
    { path: '/documents', name: 'documents', component: () => import('@/views/DocumentsView.vue'), meta: { title: '知识文档' } },
    { path: '/operations', name: 'operations', component: () => import('@/views/OperationsView.vue'), meta: { title: '运行状态' } },
    { path: '/mcp', name: 'mcp', component: () => import('@/views/McpView.vue'), meta: { title: 'MCP 服务' } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: 'API 配置' } },
    { path: '/users', name: 'users', component: () => import('@/views/UsersView.vue'), meta: { title: '用户管理' } },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!to.meta.public && !auth.authenticated) return '/login'
  if (to.path === '/login' && auth.authenticated) return '/chat'
  return true
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '控制台')} · MedOps`
})

export default router
