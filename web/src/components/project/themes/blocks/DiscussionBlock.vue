<script setup>
defineProps({ result: { type: Object, required: true }, topicLabel: { type: String, default: '议题' } })
defineEmits(['navigate'])
</script>
<template><h3 v-if="result.contextTopic" class="theme-discussion-title">{{ result.contextTopic.title }}</h3><div class="theme-timeline"><article v-for="item in result.value" :key="item.id"><small>{{ item.author_name }} · {{ item.created_at.slice(0, 10) }}</small><p>{{ item.content }}</p></article></div><button v-if="result.contextTopic" class="theme-link" :data-object-key="`topic:${result.contextTopic.id}`" @click="$emit('navigate', { kind: 'object', objectType: 'topic', id: result.contextTopic.id })">查看{{ topicLabel }}详情与完整上下文 →</button></template>
