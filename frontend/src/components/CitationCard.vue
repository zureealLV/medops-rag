<script setup lang="ts">
import { computed } from 'vue'
import { DocumentChecked } from '@element-plus/icons-vue'
import type { Citation, Evidence } from '@/types/api'

const props = defineProps<{ citation: Citation; chunks: Evidence[]; index: number }>()
const evidence = computed(() => props.chunks.find((item) => item.document_id === props.citation.document_id && item.chunk_id === props.citation.chunk_id))
const excerpt = computed(() => evidence.value?.matched_text || evidence.value?.text || '该来源已用于回答，暂无可展示摘要。')
const page = computed(() => {
  if (!evidence.value?.page_start) return ''
  if (evidence.value.page_end && evidence.value.page_end !== evidence.value.page_start) return `第 ${evidence.value.page_start}–${evidence.value.page_end} 页`
  return `第 ${evidence.value.page_start} 页`
})
</script>

<template>
  <article class="citation-card">
    <header>
      <span class="citation-index"><el-icon><DocumentChecked /></el-icon> 来源 {{ index + 1 }}</span>
      <span>{{ page || '文本证据' }}</span>
    </header>
    <h4>{{ citation.source }}</h4>
    <p>{{ excerpt }}</p>
    <footer><span>DOC-{{ citation.document_id }}</span><span>CHUNK-{{ citation.chunk_id }}</span><span v-if="evidence?.heading">{{ evidence.heading }}</span></footer>
  </article>
</template>
