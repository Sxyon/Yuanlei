<script setup>
defineProps({ block: { type: Object, required: true }, result: { type: Object, required: true } })
</script>
<template>
  <div v-if="block.variant === 'counts'" class="theme-counts">
    <div><small>正式任务</small><strong>{{ result.value.counts.workTasks }}</strong><p>{{ result.value.counts.blockedTasks }} 项受阻，需关注</p></div>
    <div><small>当前议题</small><strong>{{ result.value.counts.topics }}</strong><p>纳入状态与研讨进展分别核对</p></div>
    <div><small>有效决定</small><strong>{{ result.value.counts.approvedDecisions }}</strong><p>历史依据在详情或历史区阅读</p></div>
  </div>
  <p v-else class="theme-prose">{{ result.value.project.description || '暂无项目说明。' }}</p>
</template>
