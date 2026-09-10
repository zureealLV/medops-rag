<script setup lang="ts">
defineProps<{ label: string; value: string | number; caption: string; accent?: boolean }>()
</script>

<template>
  <article :class="['stat-card', { accent }]">
    <span>{{ label }}</span>
    <strong>{{ value }}</strong>
    <small>{{ caption }}</small>
  </article>
</template>
