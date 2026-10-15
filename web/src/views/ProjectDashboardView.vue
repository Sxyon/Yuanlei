<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import OverviewWorkspace from '@/components/project/capabilities/OverviewWorkspace.vue'
const route = useRoute(),
  projectId = computed(() => String(route.params.project_id || ''))
</script>
<template>
  <div class="project-dashboard-page">
    <OverviewWorkspace :key="projectId" :project-id="projectId" />
  </div>
</template>
<style scoped>
.project-dashboard-page {
  min-height: 100%;
  padding: 0 38px 48px;
  background: var(--gray-25);
}
@media (max-width: 768px) {
  .project-dashboard-page {
    padding: 0 16px 28px;
  }
}
</style>
