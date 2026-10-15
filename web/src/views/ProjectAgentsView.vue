<script setup>
import { useRoute } from 'vue-router'
import ProjectAgentManagePanel from '@/components/model-management/ProjectAgentManagePanel.vue'
const route=useRoute()
</script>
<template><div class="project-agents-page"><ProjectAgentManagePanel :key="String(route.params.project_id)" :project-id="String(route.params.project_id)" /></div></template>
<style scoped>.project-agents-page {padding:0 38px 48px;min-height:100%;background:var(--gray-25);} @media(max-width:768px){.project-agents-page{padding:0 16px 28px;}}</style>
