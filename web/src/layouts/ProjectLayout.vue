<script setup>
import { computed, ref, watch, onMounted, onUnmounted } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { LayoutDashboard, Workflow, ListChecks, Bot, Files, PanelLeft } from '@lucide/vue'
import { useProjectsStore } from '@/stores/projects'
import { useChatUIStore } from '@/stores/chatUI'
import { useUserStore } from '@/stores/user'
import { clearReviewScope } from '@/utils/resultReviewDrafts'

const props = defineProps({ enabled: { type: Boolean, default: true } })
const route = useRoute(), router = useRouter()
const projects = useProjectsStore(), ui = useChatUIStore(), user = useUserStore()
const mobileOpen = ref(false)
const narrow = ref(false)
let widthQuery
const updateWidth = () => { narrow.value = widthQuery.matches; mobileOpen.value = false }
onMounted(() => {
  widthQuery = window.matchMedia('(max-width:700px)')
  updateWidth()
  widthQuery.addEventListener?.('change', updateWidth)
})
onUnmounted(() => widthQuery?.removeEventListener?.('change', updateWidth))
const projectId = computed(() => String(route.params.project_id || ''))
const project = computed(() => projects.projects.find(item => item.id === projectId.value))
const preferenceKey = computed(() => JSON.stringify([user.uid, projectId.value]))
const collapsed = computed(() => Boolean(ui.projectNavigationCollapsed[preferenceKey.value]))
const items = computed(() => [
  { label: '概览', icon: LayoutDashboard, name: 'ProjectDashboardComp', active: route.name === 'ProjectDashboardComp' },
  { label: '工作台', icon: Workflow, name: 'ProjectInspectionBoardComp', active: route.name === 'ProjectInspectionBoardComp' },
  { label: '工作', icon: ListChecks, name: 'ProjectWorkTasksView', active: ['ProjectWorkTasksView', 'ProjectWorkTaskView'].includes(route.name) },
  { label: '项目智能体', icon: Bot, name: 'ProjectAgentsComp', active: ['ProjectAgentsComp', 'ProjectAgentWorkbenchView'].includes(route.name) }
])
function toggleNavigation() {
  narrow.value = window.matchMedia('(max-width:700px)').matches
  if (narrow.value) mobileOpen.value = !mobileOpen.value
  else if (user.uid) ui.projectNavigationCollapsed = { ...ui.projectNavigationCollapsed, [preferenceKey.value]: !collapsed.value }
}
async function refresh() {
  try { await projects.loadProjects() } catch { /* 项目列表 Owner 展示错误。 */ }
}
watch(() => [projectId.value, user.uid], () => { mobileOpen.value = false; if (projectId.value) void refresh() }, { immediate: true })
watch(() => route.fullPath, () => { mobileOpen.value = false })
watch([project, () => projects.hasLoaded, () => projects.error], () => {
  if (projectId.value && projects.hasLoaded && !projects.error && !project.value) clearReviewScope(user.uid, projectId.value)
})
</script>

<template>
  <section class="project-space" :class="{ 'project-collapsed': collapsed, 'project-mobile-open': mobileOpen, 'platform-page': !props.enabled }">
    <header v-if="enabled" class="project-space-header">
      <button class="project-nav-toggle" type="button" aria-label="项目导航" :aria-expanded="narrow ? mobileOpen : !collapsed" @click="toggleNavigation"><PanelLeft :size="18" /></button>
      <strong>{{ project?.name || '项目工作空间' }}</strong>
      <select v-if="project" aria-label="切换项目" :value="projectId" @change="router.push({ name: 'ProjectDashboardComp', params: { project_id: $event.target.value } })">
        <option v-for="item in projects.projects" :key="item.id" :value="item.id">{{ item.name }}</option>
      </select>
    </header>
    <div v-if="enabled && !projects.hasLoaded && !projects.error" class="project-space-state" role="status">正在读取项目…</div>
    <div v-else-if="enabled && (projects.error || !project)" class="project-space-state" role="alert">
      <p>{{ projects.error || '项目不存在或已无权访问' }}</p><a-button @click="refresh">重试</a-button>
    </div>
    <div class="project-space-body">
      <nav v-if="enabled && project" class="project-navigation" aria-label="项目工作空间导航">
        <RouterLink v-for="item in items" :key="item.name" :to="{ name: item.name, params: { project_id: projectId } }" :class="{ active: item.active }" :aria-current="item.active ? 'page' : undefined"><component :is="item.icon" :size="18" />{{ item.label }}</RouterLink>
        <RouterLink :to="{ name: 'WorkspaceComp', query: { open: project.workdir_path } }"><Files :size="18" />项目资料</RouterLink>
        <p>工作台研讨与确定依据；工作页交付和办理；智能体工作台接收与执行。</p>
      </nav>
      <div class="project-page"><slot /></div>
    </div>
  </section>
</template>

<style scoped lang="less">
.project-space { height: 100%; display: flex; flex-direction: column; min-width: 0; background: var(--gray-0); }
.project-space-header { display: flex; gap: 12px; align-items: center; padding: 8px 16px; border-bottom: 1px solid var(--gray-150); min-height: 52px; flex-wrap: wrap; strong { overflow-wrap: anywhere; } select { max-width: 240px; min-width: 0; background: var(--gray-0); color: var(--color-text); border: 1px solid var(--gray-200); border-radius: 6px; padding: 6px; margin-left: auto; } }
.project-nav-toggle { display: grid; place-items: center; border: 1px solid var(--gray-150); border-radius: 6px; background: var(--gray-0); color: var(--color-text); min-height: 36px; min-width: 36px; cursor: pointer; }
.project-space-body { display: flex; flex: 1; min-height: 0; min-width: 0; }
.project-navigation { width: 204px; flex: 0 0 204px; background: var(--gray-25); border-right: 1px solid var(--gray-150); padding: 12px; overflow-y: auto; a { display: flex; align-items: center; gap: 8px; min-height: 44px; padding: 10px; border-radius: 6px; color: var(--color-text); text-decoration: none; } a:hover, a.active { background: var(--main-10); color: var(--main-color); } p { font-size: 12px; color: var(--color-text-secondary); line-height: 1.7; margin-top: 24px; } }
.project-page { flex: 1; min-width: 0; overflow: auto; > :deep(*) { min-width: 0; } }
.project-collapsed .project-navigation { display: none; }
.project-space-state { padding: 24px; }
.platform-page { background: transparent; }

button:focus-visible, a:focus-visible, select:focus-visible { outline: 2px solid var(--main-color); outline-offset: 2px; }
@media (max-width:700px) { .project-space-header { gap: 8px; padding: 8px; select { max-width: 180px; } } .project-nav-toggle { min-width: 44px; min-height: 44px; } .project-space-body { flex-direction: column; } .project-navigation { display: none; width: 100%; flex: 0 0 auto; max-height: 45vh; } .project-mobile-open .project-navigation { display: block; } }
</style>
