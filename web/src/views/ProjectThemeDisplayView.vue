<script setup>
import { useRoute } from 'vue-router'
import ProjectThemePanel from '@/components/project/ProjectThemePanel.vue'
const route = useRoute()
</script>
<template>
  <div style="padding: 24px">
    <ProjectThemePanel :project-id="String(route.params.project_id)" />
  </div>
</template>
