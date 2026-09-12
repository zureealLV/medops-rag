<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Plus, UserFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { medopsApi } from '@/api/medops'
import type { ManagedUser } from '@/types/api'

const users = ref<ManagedUser[]>([])
const visible = ref(false)
const loading = ref(false)
const form = reactive({ name: '', email: '' })
async function load() { users.value = await medopsApi.listUsers() }
async function create() {
  loading.value = true
  try { await medopsApi.createUser(form); visible.value = false; form.name = ''; form.email = ''; await load(); ElMessage.success('用户已创建') }
  catch (error) { ElMessage.error(error instanceof Error ? error.message : '创建失败') }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <section class="surface-panel users-panel">
    <header class="panel-header"><div><p class="eyebrow">ADMIN ONLY</p><h3>用户管理</h3><p>业务用户与租户数据隔离，非管理员不会看到此界面。</p></div><el-button type="primary" @click="visible=true"><el-icon><Plus /></el-icon>新建用户</el-button></header>
    <el-table :data="users" stripe><el-table-column prop="id" label="ID" width="80"/><el-table-column label="用户"><template #default="{ row }"><div class="managed-user"><span><el-icon><UserFilled /></el-icon></span><div><b>{{ row.name }}</b><small>{{ row.email }}</small></div></div></template></el-table-column><el-table-column prop="tenant_id" label="租户"/><el-table-column label="状态" width="120"><template #default><el-tag type="success">正常</el-tag></template></el-table-column></el-table>
    <el-empty v-if="!users.length" description="当前租户还没有业务用户" />
    <el-dialog v-model="visible" title="新建业务用户" width="440"><el-form label-position="top"><el-form-item label="姓名"><el-input v-model="form.name" /></el-form-item><el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item></el-form><template #footer><el-button @click="visible=false">取消</el-button><el-button type="primary" :loading="loading" @click="create">创建</el-button></template></el-dialog>
  </section>
</template>
