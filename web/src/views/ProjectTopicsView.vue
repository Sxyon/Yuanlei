<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import TopicWorkspace from '@/components/project/capabilities/TopicWorkspace.vue'
const route = useRoute()
const projectId = computed(() => String(route.params.project_id || ''))
</script>
<template>
  <div class="project-topics-page"><TopicWorkspace :key="projectId" :project-id="projectId" /></div>
</template>
<style scoped>
.project-topics-page {
  min-height: 100%;
  padding: 0 38px 48px;
  background: var(--gray-25);
}
@media (max-width: 768px) {
  .project-topics-page {
    padding: 0 16px 28px;
  }
}
</style>
