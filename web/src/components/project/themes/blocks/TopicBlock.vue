<script setup>
import BusinessStatus from '../BusinessStatus.vue'
defineProps({ result: { type: Object, required: true }, topicLabel: { type: String, default: '议题' } })
defineEmits(['navigate'])
</script>
<template><div class="theme-prose"><h3>{{ result.value.title }}</h3><p>{{ result.value.summary || '暂无问题说明。' }}</p><small>预期产出</small><p>{{ result.value.expected_outcome || '尚未记录预期产出。' }}</p><div class="theme-focus-note">{{ topicLabel }}是议题的显示名称 · <BusinessStatus :value="result.value.progress" /></div><button class="theme-link" :data-object-key="`topic:${result.value.id}`" @click="$emit('navigate', { kind: 'object', objectType: 'topic', id: result.value.id })">查看{{ topicLabel }}详情与完整上下文 →</button></div></template>
