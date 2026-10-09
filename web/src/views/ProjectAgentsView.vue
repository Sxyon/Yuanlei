<script setup>
import { ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { projectAgentApi } from '@/apis/project_agent_api'
import PageHeader from '@/components/shared/PageHeader.vue'
const route = useRoute(), agents = ref([]), loading = ref(false), error = ref('')
let generation = 0
async function load() {
  const version = ++generation
  agents.value = []; loading.value = true; error.value = ''
  try {
    const data = await projectAgentApi.list(route.params.project_id)
    if (version === generation) agents.value = data.agents || []
  } catch (failure) { if (version === generation) error.value = failure.message || '项目智能体读取失败' }
  finally { if (version === generation) loading.value = false }
}
watch(() => route.params.project_id, load, { immediate: true })
</script>
<template>
  <div class="project-agents-page">
    <PageHeader title="项目智能体" :loading="loading" show-border><template #actions><a-button @click="load">刷新</a-button></template></PageHeader>
    <main>
      <p>进入智能体工作台查看待接受、当前执行、异常及历史工作。正式交付在工作详情办理；人的求助在跨项目收件箱处理。</p>
      <a-alert v-if="error" type="error" :message="error" show-icon />
      <p v-else-if="loading" role="status">正在读取项目智能体…</p>
      <p v-else-if="!agents.length">当前项目尚未绑定智能体，仍可直接创建人工工作。</p>
      <ul v-else><li v-for="agent in agents" :key="agent.slug"><strong>{{ agent.name || agent.slug }}</strong><RouterLink :to="{ name: 'ProjectAgentWorkbenchView', params: { project_id: route.params.project_id, agent_slug: agent.slug } }">进入工作台</RouterLink></li></ul>
      <RouterLink :to="{ name: 'ProjectWorkTasksView', params: { project_id: route.params.project_id } }">查看工作 / 新建人工工作</RouterLink>
    </main>
  </div>
</template>
<style scoped lang="less">
.project-agents-page { min-width: 0; main { padding: 24px; } p { color: var(--color-text-secondary); line-height: 1.7; } ul { list-style: none; padding: 0; } li { display: flex; justify-content: space-between; gap: 16px; padding: 16px; border-bottom: 1px solid var(--gray-150); flex-wrap: wrap; } a { color: var(--main-color); } }
</style>
