<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import AppShell from '@/components/AppShell.vue'
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<template>
  <el-config-provider :locale="zhCn">
    <RouterView v-if="route.meta.public" />
    <AppShell v-else />
  </el-config-provider>
</template>
