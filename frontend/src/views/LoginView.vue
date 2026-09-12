<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Connection, Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useAppStore } from '@/stores/app'

const router = useRouter()
const auth = useAuthStore()
const app = useAppStore()
const loading = ref(false)
const form = reactive({ ...auth.profile })

async function login() {
  if (form.authMode === 'api_key' && !form.apiKey.trim()) return ElMessage.warning('请输入 API Key')
  if (form.authMode === 'trusted_headers' && (!form.tenantId.trim() || !form.actorId.trim())) return ElMessage.warning('请填写租户和用户')
  loading.value = true
  auth.save({ ...form })
  try {
    await app.connect()
    auth.login()
    await router.replace('/chat')
  } catch (error) {
    ElMessage.error(`登录失败：${error instanceof Error ? error.message : '无法连接服务'}`)
  } finally { loading.value = false }
}
</script>

<template>
  <main class="login-screen">
    <section class="login-brand">
      <div class="login-orbit"><span>+</span><i /><i /><i /></div>
      <p>MEDICAL KNOWLEDGE AGENT</p>
      <h1>让每一次医疗知识问答<br><em>可追溯、可持续、可管理。</em></h1>
      <p class="login-copy">LangGraph 多轮状态·官方语料检索·强制引用·安全拒答</p>
    </section>
    <section class="login-card">
      <header><span class="brand-mark"><i /><i /><i /></span><div><b>MedOps RAG</b><small>身份验证中心</small></div></header>
      <h2>欢迎回来</h2><p>用组织身份或 API 密钥进入对应界面。</p>
      <el-segmented v-model="form.authMode" :options="[{ label: '本地组织', value: 'trusted_headers' }, { label: 'API Key', value: 'api_key' }]" block />
      <template v-if="form.authMode === 'trusted_headers'">
        <label><span>租户空间</span><el-input v-model="form.tenantId" size="large" placeholder="hospital-a"><template #prefix><el-icon><Connection /></el-icon></template></el-input></label>
        <label><span>用户标识</span><el-input v-model="form.actorId" size="large" placeholder="zureealLV"><template #prefix><el-icon><User /></el-icon></template></el-input></label>
      </template>
      <label v-else><span>Bearer API Key</span><el-input v-model="form.apiKey" type="password" show-password size="large" placeholder="mops_xxx.xxxxx"><template #prefix><el-icon><Lock /></el-icon></template></el-input></label>
      <el-button type="primary" size="large" :loading="loading" @click="login">验证并进入系统</el-button>
      <footer>凭据仅保存在当前会话中·管理功能按角色分离</footer>
    </section>
  </main>
</template>
