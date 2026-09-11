import { createRouter, createWebHashHistory } from 'vue-router'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/overview' },
    { path: '/overview', name: 'overview', component: () => import('@/views/OverviewView.vue'), meta: { title: '系统总览' } },
    { path: '/answer', name: 'answer', component: () => import('@/views/AnswerView.vue'), meta: { title: '证据问答' } },
    { path: '/documents', name: 'documents', component: () => import('@/views/DocumentsView.vue'), meta: { title: '知识文档' } },
    { path: '/operations', name: 'operations', component: () => import('@/views/OperationsView.vue'), meta: { title: '运行状态' } },
    { path: '/mcp', name: 'mcp', component: () => import('@/views/McpView.vue'), meta: { title: 'MCP 服务' } },
    { path: '/settings', name: 'settings', component: () => import('@/views/SettingsView.vue'), meta: { title: 'API 配置' } },
    { path: '/:pathMatch(.*)*', redirect: '/overview' },
  ],
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title ?? '控制台')} · MedOps`
})

export default router
