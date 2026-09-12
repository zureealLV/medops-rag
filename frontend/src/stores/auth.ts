import { defineStore } from 'pinia'
import { reactive, ref } from 'vue'
import type { ConnectionProfile } from '@/types/api'

const defaults: ConnectionProfile = {
  authMode: 'trusted_headers',
  tenantId: 'hospital-a',
  actorId: 'zureealLV',
  apiKey: '',
}

function readProfile(): ConnectionProfile {
  try {
    const stored = JSON.parse(localStorage.getItem('medops-profile') ?? '{}') as Partial<ConnectionProfile>
    return { ...defaults, ...stored, apiKey: sessionStorage.getItem('medops-api-key') ?? '' }
  } catch {
    return { ...defaults }
  }
}

export const useAuthStore = defineStore('auth', () => {
  const profile = reactive<ConnectionProfile>(readProfile())
  const authenticated = ref(sessionStorage.getItem('medops-authenticated') === '1')

  function save(next: ConnectionProfile) {
    Object.assign(profile, next)
    const { apiKey: _apiKey, ...persistent } = next
    localStorage.setItem('medops-profile', JSON.stringify(persistent))
    if (next.apiKey) sessionStorage.setItem('medops-api-key', next.apiKey)
    else sessionStorage.removeItem('medops-api-key')
  }

  function login() {
    authenticated.value = true
    sessionStorage.setItem('medops-authenticated', '1')
  }

  function logout() {
    authenticated.value = false
    sessionStorage.removeItem('medops-authenticated')
    sessionStorage.removeItem('medops-api-key')
    profile.apiKey = ''
  }

  return { profile, authenticated, save, login, logout }
})
