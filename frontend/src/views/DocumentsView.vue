<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { DocumentAdd, Files, FolderAdd, Search, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { medopsApi } from '@/api/medops'
import { useAppStore } from '@/stores/app'
import type { DocumentSummary } from '@/types/api'

const app = useAppStore()
const documents = ref<DocumentSummary[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const query = ref('')
const loading = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const createVisible = ref(false)
const newKb = ref({ name: '', description: '' })
let request: AbortController | null = null
let searchTimer: number | undefined

const activeKb = computed(() => app.activeKnowledgeBase)
const canManage = computed(() => ['admin', 'editor'].includes(app.identity?.role ?? ''))

async function loadDocuments() {
  if (!app.activeKbId) {
    documents.value = []
    total.value = 0
    return
  }
  request?.abort()
  request = new AbortController()
  loading.value = true
  try {
    const result = await medopsApi.listDocuments(app.activeKbId, {
      limit: pageSize.value,
      offset: (page.value - 1) * pageSize.value,
      query: query.value.trim(),
    }, request.signal)
    documents.value = result.items
    total.value = result.total
    if (page.value > 1 && !result.items.length && result.total) page.value = Math.ceil(result.total / pageSize.value)
  } catch (error) {
    if ((error as Error).name !== 'AbortError') ElMessage.error(`读取文档失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    loading.value = false
  }
}

watch(() => app.activeKbId, () => { page.value = 1; query.value = ''; void loadDocuments() })
watch(query, () => {
  window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { page.value = 1; void loadDocuments() }, 250)
})

async function createKnowledgeBase() {
  const name = newKb.value.name.trim()
  if (!name) return ElMessage.warning('请输入知识库名称')
  try {
    const created = await medopsApi.createKnowledgeBase({ name, description: newKb.value.description.trim() || null })
    app.activeKbId = created.id
    await app.loadKnowledgeBases()
    createVisible.value = false
    newKb.value = { name: '', description: '' }
    app.log('创建知识库', `KB-${created.id}`)
    ElMessage.success(`知识库“${created.name}”已创建`)
  } catch (error) {
    ElMessage.error(`创建失败：${error instanceof Error ? error.message : '未知错误'}`)
  }
}

async function uploadFiles(rawFiles: File[]) {
  if (!app.activeKbId) return ElMessage.warning('请先选择知识库')
  if (!rawFiles.length) return
  uploading.value = true
  uploadProgress.value = 0
  let cursor = 0
  let completed = 0
  let failed = 0
  const kbId = app.activeKbId

  // Two workers prevent a large selection from flooding the API while still reducing total wait time.
  async function worker() {
    while (cursor < rawFiles.length) {
      const file = rawFiles[cursor++]
      if (!file) continue
      try { await medopsApi.uploadDocument(kbId, file) } catch { failed += 1 }
      completed += 1
      uploadProgress.value = Math.round((completed / rawFiles.length) * 100)
    }
  }

  try {
    await Promise.all(Array.from({ length: Math.min(2, rawFiles.length) }, worker))
    page.value = 1
    await loadDocuments()
    app.log('文档上传', `${completed - failed}/${rawFiles.length}`)
    if (failed) ElMessage.warning(`${completed - failed} 个成功，${failed} 个失败`)
    else ElMessage.success(`已处理 ${completed} 个文件`)
  } finally {
    uploading.value = false
  }
}

function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  void uploadFiles(Array.from(input.files ?? []))
  input.value = ''
}

function onDrop(event: DragEvent) {
  void uploadFiles(Array.from(event.dataTransfer?.files ?? []))
}

onMounted(loadDocuments)
onBeforeUnmount(() => { request?.abort(); window.clearTimeout(searchTimer) })
</script>

<template>
  <div class="page-stack document-page">
    <header class="section-heading">
      <div><p class="eyebrow">TENANT KNOWLEDGE</p><h2>知识库与文档</h2><p>文档采用服务端分页加载，大规模知识库不会阻塞浏览器。</p></div>
      <el-button v-if="canManage" type="primary" size="large" @click="createVisible = true"><el-icon><FolderAdd /></el-icon>新建知识库</el-button>
    </header>

    <div class="documents-layout">
      <aside class="surface-panel kb-sidebar">
        <header class="panel-header"><h3>知识库</h3><el-tag round>{{ app.knowledgeBases.length }}</el-tag></header>
        <div class="kb-list">
          <button v-for="kb in app.knowledgeBases" :key="kb.id" :class="{ active: kb.id === app.activeKbId }" type="button" @click="app.activeKbId = kb.id">
            <span><el-icon><Files /></el-icon></span><div><b>{{ kb.name }}</b><small>{{ kb.description || `Tenant: ${kb.tenant_id}` }}</small></div>
          </button>
          <el-empty v-if="!app.knowledgeBases.length" description="暂无知识库" :image-size="64" />
        </div>
      </aside>

      <section class="surface-panel docs-panel">
        <header class="panel-header document-panel-header">
          <div><p class="eyebrow">{{ activeKb ? `KB-${String(activeKb.id).padStart(2, '0')}` : 'SELECT SPACE' }}</p><h3>{{ activeKb?.name || '请选择知识库' }}</h3></div>
          <label v-if="canManage" :class="['el-button el-button--primary', { 'is-disabled': !activeKb || uploading }]">
            <el-icon><DocumentAdd /></el-icon><span>{{ uploading ? '正在上传' : '上传文件' }}</span>
            <input class="sr-only" type="file" multiple :disabled="!activeKb || uploading" accept=".txt,.md,.csv,.json,.jsonl,.pdf,.docx,.pptx,.png,.jpg,.jpeg,.webp" @change="chooseFiles">
          </label>
        </header>

        <div v-if="canManage" class="drop-zone" @dragover.prevent @drop.prevent="onDrop">
          <el-icon><UploadFilled /></el-icon><div><b>拖放资料到这里</b><span>支持文本、Office、PDF 与图片，单文件限制由服务端统一校验</span></div>
        </div>
        <el-progress v-if="uploading" :percentage="uploadProgress" :stroke-width="8" />

        <div class="document-toolbar">
          <el-input v-model="query" clearable maxlength="100" placeholder="按标题或来源搜索" :prefix-icon="Search" />
          <span>共 {{ total.toLocaleString() }} 份文档</span>
        </div>

        <el-table v-loading="loading" :data="documents" height="min(55vh, 580px)" stripe table-layout="fixed" empty-text="这个知识库还没有匹配的文档">
          <el-table-column label="文档" min-width="260">
            <template #default="{ row }"><div class="document-name"><b>{{ row.title }}</b><small>{{ row.mime_type }}</small></div></template>
          </el-table-column>
          <el-table-column prop="source" label="来源" min-width="180" show-overflow-tooltip />
          <el-table-column label="切片 / 证据" width="150">
            <template #default="{ row }"><b>{{ row.chunk_count }}</b> chunks<br><small>{{ row.artifact_count }} artifacts</small></template>
          </el-table-column>
          <el-table-column label="摄取状态" width="150">
            <template #default="{ row }"><el-tag :type="row.ingest_status === 'succeeded' ? 'success' : row.ingest_status === 'failed' ? 'danger' : 'info'" effect="light">{{ row.ingest_status }}</el-tag><small class="parser-label">{{ row.parser }}</small></template>
          </el-table-column>
        </el-table>

        <div class="pagination-row">
          <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" background @change="loadDocuments" />
        </div>
      </section>
    </div>

    <el-dialog v-model="createVisible" title="新建知识库" width="min(520px, 92vw)">
      <el-form label-position="top" @submit.prevent="createKnowledgeBase">
        <el-form-item label="名称"><el-input v-model="newKb.name" maxlength="120" show-word-limit placeholder="例如：监护设备使用与维护" /></el-form-item>
        <el-form-item label="说明"><el-input v-model="newKb.description" type="textarea" :rows="4" maxlength="500" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible = false">取消</el-button><el-button type="primary" @click="createKnowledgeBase">创建</el-button></template>
    </el-dialog>
  </div>
</template>
