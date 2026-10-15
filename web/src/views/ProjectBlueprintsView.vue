<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import BlueprintWorkspace from '@/components/project/capabilities/BlueprintWorkspace.vue'
const route = useRoute()
const projectId = computed(() => String(route.params.project_id || ''))
</script>
<template>
  <div class="project-blueprints-page">
    <BlueprintWorkspace :key="projectId" :project-id="projectId" />
  </div>
</template>
<style scoped>
.project-blueprints-page {
  height: 100%;
  min-height: 0;
  padding: 0 38px 48px;
  background: var(--gray-25);
}
@media (max-width: 768px) {
  .project-blueprints-page {
    padding: 0 16px 28px;
  }
}
</style>
