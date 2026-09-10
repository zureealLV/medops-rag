<script setup lang="ts">
import { CircleCheck, CircleClose, Loading } from '@element-plus/icons-vue'
import type { AgentStep } from '@/types/api'

defineProps<{ steps: AgentStep[] }>()

const nodeLabels: Record<string, string> = {
  route_question: '理解问题',
  apply_safety_policy: '安全边界校验',
  select_read_only_tool: '选择知识工具',
  execute_grounded_medical_answer: '检索可信证据',
  verify_grounding: '核验回答与引用',
}
</script>

<template>
  <section class="trace-section">
    <div class="section-title"><span>处理轨迹</span><small>{{ steps.length }} 个步骤</small></div>
    <div class="trace-list">
      <div v-for="(step, index) in steps" :key="`${step.node}-${index}`" class="trace-step">
        <div :class="['trace-icon', step.status]">
          <el-icon v-if="step.status === 'completed'"><CircleCheck /></el-icon>
          <el-icon v-else-if="step.status === 'failed'"><CircleClose /></el-icon>
          <el-icon v-else><Loading /></el-icon>
        </div>
        <div><b>{{ nodeLabels[step.node] ?? step.node }}</b><small>{{ step.detail || '步骤已完成' }}</small></div>
        <time>{{ Number(step.duration_ms || 0).toFixed(1) }} ms</time>
      </div>
    </div>
  </section>
</template>
