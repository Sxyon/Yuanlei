<script setup>
import { computed } from 'vue'
const props = defineProps({ result: { type: Object, required: true } })
const entries = computed(() => props.result.value && typeof props.result.value === 'object' && !Array.isArray(props.result.value) ? Object.entries(props.result.value) : [])
const metrics = computed(() => entries.value.filter(([, value]) => typeof value === 'number'))
const text = computed(() => entries.value.filter(([, value]) => typeof value === 'string'))
</script>
<template><p class="theme-meta">{{ result.metadata.mediaType }} · {{ result.metadata.size }} bytes</p><div v-if="metrics.length" class="theme-file-metrics"><div v-for="[key, value] in metrics" :key="key"><small>{{ key }}</small><strong>{{ value }}</strong></div></div><p v-for="[key, value] in text" :key="key" class="theme-prose">{{ key }}：{{ value }}</p><details class="theme-section-line" :open="!entries.length"><summary>查看资料 JSON 原文与局限</summary><pre>{{ JSON.stringify(result.value, null, 2) }}</pre></details></template>
