<script setup>
import { computed, inject, nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PlanWorkspace from '@/components/project/capabilities/PlanWorkspace.vue'
import ReportWorkspace from '@/components/project/capabilities/ReportWorkspace.vue'
import ProjectFilesWorkspace from '@/components/project/capabilities/ProjectFilesWorkspace.vue'
import ProjectSettingsModal from '@/components/ProjectSettingsModal.vue'
import ProjectThemeSelection from '@/components/project/ProjectThemeSelection.vue'
import ProjectThemeManager from '@/components/project/ProjectThemeManager.vue'
import { Modal, message } from 'ant-design-vue'
import { projectApi } from '@/apis/project_api'
import { useChatThreadsStore } from '@/stores/chatThreads'
import { useProjectsStore } from '@/stores/projects'
const router = useRouter(), chatThreads = useChatThreadsStore()
const route = useRoute(),
  projects = useProjectsStore(),
  theme = inject('projectThemeContext', null)
const themeManager = ref(null), themeSelection = ref(null), settings = ref(null), themeDialog = ref('')
async function closeThemeDialog() { const active = themeDialog.value === 'select' ? themeSelection.value : themeManager.value; if (!active || await active.canDiscard()) themeDialog.value = '' }
const projectId = computed(() => String(route.params.project_id))
const project = computed(() => projects.projects.find((item) => item.id === projectId.value))
/** 项目删除沿原API及会话清理Owner，文件保留规则不变。 */
function confirmDeleteProject() {
  const target = project.value
  if (!target) return
  Modal.confirm({
    title: `删除项目“${target.name}”？`,
    content: '项目中的对话会被删除，项目文件夹和其中的文件会保留。',
    okText: '删除项目', okButtonProps: { danger: true }, cancelText: '取消',
    async onOk() {
      try {
        await projectApi.deleteProject(target.id)
        chatThreads.removeThreadsByProject(target.id)
        projects.removeProject(target.id)
        await nextTick()
        await router.replace({ name: 'ProjectsComp' })
        message.success('项目及其中对话已删除，项目文件夹已保留')
      } catch (cause) { message.error(cause?.message || '删除项目失败'); throw cause }
    }
  })
}
</script>
<template>
  <div class="project-capability-page">
    <PlanWorkspace v-if="route.name === 'ProjectPlans'" :key="projectId" :project-id="projectId" />
    <ReportWorkspace
      v-else-if="route.name === 'ProjectReports'"
      :key="projectId"
      :project-id="projectId"
    />
    <ProjectFilesWorkspace
      v-else-if="route.name === 'ProjectFiles'"
      :key="projectId"
      :project-id="projectId"
    />
    <template v-else-if="route.name === 'ProjectSettings' && project">
      <ProjectSettingsModal ref="settings" :key="projectId" :open="true" :project="project" embedded @saved="projects.loadProjects()">
        <template #project-aside><div class="settings-aside-stack"><section class="settings-panel"><h2>当前项目主题</h2><p>{{ theme?.selection?.source?.name || '内置完整基础界面' }}<span v-if="theme?.selection?.version"> · {{ theme.selection.version.version }}</span></p><p class="settings-help">候选、发布版本与项目选择分别维护。</p><div class="settings-actions"><a-button @click="themeDialog = 'select'">选择与预览主题</a-button><a-button type="text" @click="themeDialog = 'maintain'">维护项目候选</a-button></div></section>
          <section class="settings-panel settings-danger"><h2>项目管理</h2><p class="settings-help">删除项目会删除其中的对话，项目文件夹保留。</p><a-button danger @click="confirmDeleteProject">删除项目</a-button></section></div></template>
      </ProjectSettingsModal>
      <a-modal :open="!!themeDialog" :title="themeDialog === 'select' ? '选择与预览项目主题' : '维护项目主题候选'" :footer="null" :width="1100" :mask-closable="false" :destroy-on-close="true" @cancel="closeThemeDialog">
        <ProjectThemeSelection v-show="themeDialog === 'select'" ref="themeSelection" :project-id="projectId" :projects="[project]" stay-in-project  @cancel="themeDialog = ''"  />
        <ProjectThemeManager v-show="themeDialog === 'maintain'" ref="themeManager" :project-id="projectId" :projects="[project]" stay-in-project @catalog-changed="themeSelection?.refreshCatalog()"  />
      </a-modal>
    </template>
  </div>
</template>
<style scoped lang="less">
.project-capability-page {
  min-height: 100%;
  padding: 0 38px 48px;
  background: var(--gray-25);
}
.settings-theme {
  margin-top: 24px;
  background: var(--gray-0);
  padding: 20px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
}
.settings-theme > summary {
  cursor: pointer;
  margin-bottom: 20px;
}
@media (max-width: 768px) {
  .project-capability-page {
    padding: 0 16px 28px;
  }
}

.settings-aside-stack { display:grid; gap:20px; }.settings-panel { padding:24px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; min-width:0; h2 { font-size:19px; margin:0 0 18px; } p { margin:12px 0; } details { margin-top:16px; >summary { cursor:pointer; font-size:13px; } } }.settings-help { font-size:13px; color:var(--color-text-secondary); overflow-wrap:anywhere; }.settings-actions { display:flex; gap:8px; flex-wrap:wrap; }

.settings-aside-stack { display:flex; flex-direction:column; gap:24px; }.settings-danger { border-color:var(--gray-150); }
</style>
