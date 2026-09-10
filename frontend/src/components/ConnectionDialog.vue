<script setup lang="ts">
import { reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import type { ConnectionProfile } from '@/types/api'

const visible = defineModel<boolean>({ required: true })
const emit = defineEmits<{ connected: [] }>()
const auth = useAuthStore()
const form = reactive<ConnectionProfile>({ ...auth.profile })

watch(visible, (open) => {
  if (open) Object.assign(form, auth.profile)
})

function save() {
  if (form.authMode === 'trusted_headers' && (!form.tenantId.trim() || !form.actorId.trim())) {
    ElMessage.warning('Tenant ID 和 Actor ID 不能为空')
    return
  }
  if (form.authMode === 'api_key' && !form.apiKey.trim()) {
    ElMessage.warning('请输入 API Key')
    return
  }
  auth.save({
    authMode: form.authMode,
    tenantId: form.tenantId.trim(),
    actorId: form.actorId.trim(),
    apiKey: form.apiKey.trim(),
  })
  visible.value = false
  emit('connected')
  ElMessage.success('连接配置已更新')
}
</script>

<template>
  <el-dialog v-model="visible" title="连接设置" width="min(520px, 92vw)" append-to-body>
    <div class="dialog-intro">凭据只用于当前浏览器会话；API Key 不写入 localStorage。</div>
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="认证模式">
        <el-segmented v-model="form.authMode" :options="[{ label: '可信 Header', value: 'trusted_headers' }, { label: 'Bearer API Key', value: 'api_key' }]" block />
      </el-form-item>
      <template v-if="form.authMode === 'trusted_headers'">
        <el-form-item label="Tenant ID"><el-input v-model="form.tenantId" maxlength="64" /></el-form-item>
        <el-form-item label="Actor ID"><el-input v-model="form.actorId" maxlength="80" /></el-form-item>
      </template>
      <el-form-item v-else label="API Key">
        <el-input v-model="form.apiKey" type="password" show-password autocomplete="off" placeholder="mops_prefix.secret" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="save">保存并连接</el-button>
    </template>
  </el-dialog>
</template>
