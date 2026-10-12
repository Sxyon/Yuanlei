<script setup>
defineProps({ value: { type: String, default: '' } })
const labels = { open: '研讨中', decided: '已形成决策', closed: '已关闭', canonical: '已纳入', proposed: '待纳入', rejected: '已拒绝', approved: '已批准', superseded: '已被替代', revoked: '已撤销', todo: '待开始', in_progress: '进行中', blocked: '受阻', done: '已完成', cancelled: '已取消' }
</script>
<template><span class="theme-status" :class="{ warning: ['blocked', 'proposed'].includes(value), success: value === 'approved', info: value === 'in_progress' }">{{ labels[value] || value || '未知' }}</span></template>
