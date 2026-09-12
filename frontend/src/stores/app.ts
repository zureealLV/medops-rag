import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { medopsApi } from '@/api/medops'
import type { Health, Identity, KnowledgeBase, Metrics } from '@/types/api'

export interface ActivityItem { action: string; outcome: string; time: string }

export const useAppStore = defineStore('app', () => {
  const health = ref<Health | null>(null)
  const identity = ref<Identity | null>(null)
  const knowledgeBases = ref<KnowledgeBase[]>([])
  const activeKbId = ref<number | null>(null)
  const metrics = ref<Metrics | null>(null)
  const connecting = ref(false)
  const connectionError = ref('')
  const activity = ref<ActivityItem[]>([])

  const activeKnowledgeBase = computed(() => knowledgeBases.value.find((item) => item.id === activeKbId.value) ?? null)
  const online = computed(() => health.value?.status === 'ok' && !connectionError.value)

  function log(action: string, outcome = 'OK') {
    activity.value.unshift({ action, outcome, time: new Date().toLocaleTimeString('zh-CN', { hour12: false }) })
    activity.value = activity.value.slice(0, 10)
  }

  async function loadKnowledgeBases() {
    knowledgeBases.value = await medopsApi.listKnowledgeBases()
    if (!knowledgeBases.value.some((item) => item.id === activeKbId.value)) {
      const preferred = knowledgeBases.value.find((item) => /中国官方医疗/.test(item.name))
        ?? knowledgeBases.value.find((item) => /华佗中文医学/.test(item.name))
        ?? knowledgeBases.value.find((item) => /MedlinePlus|器械|医疗|医学/.test(item.name))
        ?? knowledgeBases.value[0]
      activeKbId.value = preferred?.id ?? null
    }
  }

  async function loadMetrics() {
    metrics.value = await medopsApi.metrics()
  }

  async function connect() {
    connecting.value = true
    connectionError.value = ''
    try {
      const [healthResult, identityResult] = await Promise.all([medopsApi.health(), medopsApi.whoami()])
      health.value = healthResult
      identity.value = identityResult
      await Promise.all([loadKnowledgeBases(), loadMetrics().catch(() => undefined)])
      log('服务连接', `V${healthResult.version}`)
    } catch (error) {
      connectionError.value = error instanceof Error ? error.message : '连接失败'
      log('服务连接', 'FAILED')
      throw error
    } finally {
      connecting.value = false
    }
  }

  return {
    health, identity, knowledgeBases, activeKbId, activeKnowledgeBase, metrics,
    connecting, connectionError, activity, online, log, connect, loadKnowledgeBases, loadMetrics,
  }
})
