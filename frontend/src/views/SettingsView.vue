<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { Check, Connection, CopyDocument, Key, Lock, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { medopsApi } from '@/api/medops'
import type {
  ModelConfigInput,
  ModelConfigTestResult,
  ModelConfigView,
  ModelProviderName,
} from '@/types/api'

interface ProviderPreset {
  value: ModelProviderName
  label: string
  caption: string
  baseUrl: string
  model: string
}

const presets: ProviderPreset[] = [
  { value: 'deepseek', label: 'DeepSeek', caption: 'OpenAI-compatible', baseUrl: 'https://api.deepseek.com', model: 'deepseek-v4-flash' },
  { value: 'openai', label: 'OpenAI', caption: 'Official API', baseUrl: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
  { value: 'qwen', label: '通义千问', caption: 'DashScope compatible', baseUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
  { value: 'zhipu', label: '智谱 GLM', caption: 'BigModel compatible', baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  { value: 'ollama', label: 'Ollama', caption: 'Local OpenAI bridge', baseUrl: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:7b' },
  { value: 'custom', label: '自定义', caption: 'OpenAI-compatible', baseUrl: 'https://provider.example/v1', model: 'custom-model' },
]

const loading = ref(false)
const testing = ref(false)
const applying = ref(false)
const current = ref<ModelConfigView | null>(null)
const testResult = ref<ModelConfigTestResult | null>(null)
const form = reactive({
  provider: 'deepseek' as ModelProviderName,
  model_name: '',
  base_url: '',
  api_key: '',
  clear_api_key: false,
  vision_enabled: false,
})

const selectedPreset = computed(() => presets.find((item) => item.value === form.provider) ?? presets[5])
const keyLabel = computed(() => {
  if (!current.value?.api_key_configured) return '未配置'
  return current.value.api_key_source === 'runtime' ? '当前进程' : '环境变量'
})

function payload(): ModelConfigInput {
  return {
    provider: form.provider,
    model_name: form.model_name.trim(),
    base_url: form.base_url.trim().replace(/\/$/, ''),
    api_key: form.api_key.trim() || undefined,
    clear_api_key: form.clear_api_key,
    vision_enabled: form.vision_enabled,
  }
}

function hydrate(config: ModelConfigView) {
  current.value = config
  form.provider = config.provider
  form.model_name = config.model_name
  form.base_url = config.base_url
  form.api_key = ''
  form.clear_api_key = false
  form.vision_enabled = config.vision_enabled
}

async function load() {
  loading.value = true
  try {
    hydrate(await medopsApi.modelConfig())
  } catch (error) {
    ElMessage.error(`读取配置失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    loading.value = false
  }
}

function chooseProvider(provider: ModelProviderName) {
  const preset = presets.find((item) => item.value === provider)
  if (!preset) return
  form.provider = provider
  form.base_url = preset.baseUrl
  form.model_name = preset.model
  testResult.value = null
}

function validate(): boolean {
  if (!form.model_name.trim() || !form.base_url.trim()) {
    ElMessage.warning('模型名称和 Base URL 不能为空')
    return false
  }
  return true
}

async function testConnection() {
  if (!validate()) return
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await medopsApi.testModelConfig(payload())
    ElMessage.success(`连接成功，${testResult.value.latency_ms.toFixed(1)} ms`)
  } catch (error) {
    ElMessage.error(`连接测试失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    testing.value = false
  }
}

async function applyConfig() {
  if (!validate()) return
  applying.value = true
  try {
    hydrate(await medopsApi.applyModelConfig(payload()))
    testResult.value = null
    ElMessage.success('已应用到当前 MedOps 进程')
  } catch (error) {
    ElMessage.error(`应用失败：${error instanceof Error ? error.message : '未知错误'}`)
  } finally {
    applying.value = false
  }
}

async function copyEnv() {
  const lines = [
    `MODEL_BASE_URL=${form.base_url.trim().replace(/\/$/, '')}`,
    `MODEL_NAME=${form.model_name.trim()}`,
    form.api_key.trim() ? `MODEL_API_KEY=${form.api_key.trim()}` : 'MODEL_API_KEY=<在本机填写，不要提交到 Git>',
    `MODEL_VISION_ENABLED=${String(form.vision_enabled)}`,
  ]
  await navigator.clipboard.writeText(lines.join('\n'))
  ElMessage.success('环境变量模板已复制')
}

onMounted(load)
</script>

<template>
  <div class="page-stack provider-page" v-loading="loading">
    <section class="provider-hero surface-panel">
      <div>
        <p class="eyebrow">MODEL PROVIDER · ADMIN ONLY</p>
        <h2>API 与模型配置</h2>
        <p>像常见 RAG 控制台一样完成提供商选择、连接测试和配置切换，但 API Key 不回显、不写入浏览器持久化，也不明文落库。</p>
      </div>
      <div class="provider-state">
        <span class="state-orb"><el-icon><Connection /></el-icon></span>
        <div><small>ACTIVE PROVIDER</small><b>{{ selectedPreset.label }}</b><code>{{ current?.model_name ?? 'loading' }}</code></div>
        <el-tag :type="current?.api_key_configured ? 'success' : 'info'">Key {{ keyLabel }}</el-tag>
      </div>
    </section>

    <section class="provider-layout">
      <article class="surface-panel provider-picker">
        <header class="panel-header"><div><p class="eyebrow">PROVIDER PRESETS</p><h3>选择提供商</h3></div></header>
        <button
          v-for="preset in presets"
          :key="preset.value"
          type="button"
          :class="['provider-option', { active: form.provider === preset.value }]"
          @click="chooseProvider(preset.value)"
        >
          <span>{{ preset.label.slice(0, 2).toUpperCase() }}</span>
          <div><b>{{ preset.label }}</b><small>{{ preset.caption }}</small></div>
          <el-icon v-if="form.provider === preset.value"><Check /></el-icon>
        </button>
      </article>

      <article class="surface-panel provider-form-panel">
        <header class="panel-header">
          <div><p class="eyebrow">RUNTIME CONFIG</p><h3>当前活动配置</h3></div>
          <el-button text :icon="Refresh" @click="load">重新读取</el-button>
        </header>

        <el-alert
          title="会话级应用：立即影响 HTTP 问答与 MCP 工具；服务重启后恢复 .env 配置。"
          type="warning"
          :closable="false"
          show-icon
        />

        <el-form class="provider-form" label-position="top" @submit.prevent="applyConfig">
          <div class="form-grid">
            <el-form-item label="模型名称" required>
              <el-input v-model="form.model_name" maxlength="200" placeholder="deepseek-v4-flash" />
            </el-form-item>
            <el-form-item label="视觉输入">
              <div class="switch-row"><el-switch v-model="form.vision_enabled" /><span>允许向 Provider 发送受限图片证据</span></div>
            </el-form-item>
          </div>
          <el-form-item label="Base URL" required>
            <el-input v-model="form.base_url" maxlength="2048" placeholder="https://api.deepseek.com">
              <template #prefix><el-icon><Connection /></el-icon></template>
            </el-input>
            <small class="field-note">填写 API 根地址，不要包含 <code>/chat/completions</code>。</small>
          </el-form-item>
          <el-form-item label="API Key">
            <el-input
              v-model="form.api_key"
              type="password"
              show-password
              maxlength="4096"
              autocomplete="new-password"
              :placeholder="current?.api_key_configured ? '已配置；留空保持不变' : 'sk-...（本地模型可留空）'"
              :disabled="form.clear_api_key"
            >
              <template #prefix><el-icon><Key /></el-icon></template>
            </el-input>
            <div class="key-controls">
              <small><el-icon><Lock /></el-icon> 服务端永不回传原 Key；测试请求也不会写入审计日志。</small>
              <el-checkbox v-model="form.clear_api_key">清除当前 Key</el-checkbox>
            </div>
          </el-form-item>
        </el-form>

        <div v-if="testResult" class="test-success">
          <el-icon><Check /></el-icon>
          <div><b>连接成功 · {{ testResult.latency_ms.toFixed(1) }} ms</b><small>{{ testResult.endpoint }} · {{ testResult.response_preview }}</small></div>
        </div>

        <footer class="provider-actions">
          <el-button :icon="CopyDocument" @click="copyEnv">复制 .env 模板</el-button>
          <el-button :loading="testing" @click="testConnection">测试连接</el-button>
          <el-button type="primary" :loading="applying" @click="applyConfig">应用到当前进程</el-button>
        </footer>
      </article>
    </section>

    <section class="provider-notes">
      <article><b>01 · 不回显密钥</b><span>接口只返回“是否已配置”和来源，避免前端或截图泄密。</span></article>
      <article><b>02 · 管理员边界</b><span>API Key 身份模式下，viewer/editor 无法读取、测试或修改 Provider。</span></article>
      <article><b>03 · 显式持久化</b><span>若要跨重启保留，请复制模板写入本机 `.env`，该文件已被 Git 忽略。</span></article>
    </section>
  </div>
</template>

<style scoped>
.provider-page { gap: 18px; }
.provider-hero { min-height: 220px; padding: 38px 44px; display: grid; grid-template-columns: 1.25fr .75fr; align-items: center; gap: 30px; overflow: hidden; background: radial-gradient(circle at 5% 0, rgba(255,122,102,.13), transparent 32%), radial-gradient(circle at 95% 0, rgba(72,201,238,.17), transparent 35%), rgba(255,255,255,.92); }
.provider-hero h2 { margin: 0; font-family: Georgia, "Noto Serif SC", serif; font-size: clamp(36px, 4vw, 58px); font-weight: 500; letter-spacing: -.05em; }
.provider-hero > div > p:not(.eyebrow) { max-width: 720px; margin: 16px 0 0; color: var(--muted); font-size: 13px; line-height: 1.8; }
.provider-state { min-width: 0; padding: 22px; display: grid; grid-template-columns: 56px 1fr auto; align-items: center; gap: 14px; border: 1px solid rgba(211,220,243,.9); border-radius: 22px; background: rgba(255,255,255,.74); box-shadow: 0 15px 35px rgba(68,79,126,.09); }
.state-orb { width: 54px; height: 54px; display: grid; place-items: center; border-radius: 18px; color: #fff; background: linear-gradient(145deg, #536fee, #2bbfa0); font-size: 24px; }
.provider-state small,.provider-state b,.provider-state code { display: block; }.provider-state small { color: var(--muted); font-size: 8px; letter-spacing: .14em; }.provider-state b { margin-top: 4px; font-size: 16px; }.provider-state code { margin-top: 4px; overflow: hidden; color: #566582; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.provider-layout { display: grid; grid-template-columns: 300px minmax(0,1fr); gap: 18px; align-items: start; }.provider-picker { display: grid; gap: 7px; }.provider-picker .panel-header { margin-bottom: 8px; }
.provider-option { width: 100%; padding: 12px; display: grid; grid-template-columns: 38px 1fr 18px; align-items: center; gap: 10px; border: 1px solid transparent; border-radius: 13px; color: #53617d; text-align: left; background: transparent; cursor: pointer; }.provider-option:hover { background: #f5f8ff; }.provider-option.active { border-color: #bec9f8; color: #354bc0; background: linear-gradient(135deg, #eef1ff, #edfbf8); }.provider-option > span { width: 36px; height: 36px; display: grid; place-items: center; border-radius: 11px; color: #fff; background: linear-gradient(135deg, #536fee, #48c9ee); font-size: 10px; font-weight: 800; }.provider-option b,.provider-option small { display: block; }.provider-option b { font-size: 12px; }.provider-option small { margin-top: 3px; color: var(--muted); font-size: 9px; }
.provider-form-panel { min-height: 590px; }.provider-form { margin-top: 22px; }.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }.switch-row { min-height: 40px; display: flex; align-items: center; gap: 10px; color: #67738e; font-size: 11px; }.field-note { margin-top: 7px; color: var(--muted); font-size: 9px; }.key-controls { width: 100%; margin-top: 8px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }.key-controls small { display: inline-flex; align-items: center; gap: 5px; color: #6e7a95; font-size: 9px; }
.test-success { margin-top: 8px; padding: 14px; display: flex; align-items: center; gap: 11px; border: 1px solid #bfe7d8; border-radius: 13px; color: #18775e; background: #edf9f5; }.test-success > .el-icon { font-size: 20px; }.test-success b,.test-success small { display: block; }.test-success b { font-size: 12px; }.test-success small { margin-top: 4px; color: #5f8379; font-size: 9px; }
.provider-actions { margin-top: 24px; padding-top: 20px; display: flex; justify-content: flex-end; gap: 9px; border-top: 1px solid var(--line); }.provider-notes { display: grid; grid-template-columns: repeat(3,1fr); gap: 12px; }.provider-notes article { padding: 18px; border: 1px solid var(--line); border-radius: 18px; background: rgba(255,255,255,.78); }.provider-notes b,.provider-notes span { display: block; }.provider-notes b { color: #4d63d4; font-size: 11px; }.provider-notes span { margin-top: 7px; color: var(--muted); font-size: 10px; line-height: 1.6; }
@media (max-width: 960px) { .provider-hero,.provider-layout { grid-template-columns: 1fr; }.provider-picker { grid-template-columns: repeat(2,1fr); }.provider-picker .panel-header { grid-column: 1/-1; }.provider-notes { grid-template-columns: 1fr; } }
@media (max-width: 560px) { .provider-hero { padding: 25px; }.provider-state { grid-template-columns: 50px 1fr; }.provider-state .el-tag { grid-column: 1/-1; justify-self: start; }.provider-picker,.form-grid { grid-template-columns: 1fr; }.key-controls,.provider-actions { align-items: stretch; flex-direction: column; }.provider-actions .el-button { width: 100%; margin-left: 0; } }
</style>
