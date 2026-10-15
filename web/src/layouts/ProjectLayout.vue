<script setup>
import { computed, provide, ref, shallowRef, watch, onMounted, onUnmounted } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { LayoutDashboard, BookOpen, MessageSquare, Workflow, ListChecks, Bot, Files, Settings, Activity, PanelLeft, ArrowLeft } from '@lucide/vue'
import { useProjectsStore } from '@/stores/projects'
import { useChatUIStore } from '@/stores/chatUI'
import { useUserStore } from '@/stores/user'
import { projectThemeApi } from '@/apis/project_theme_api'
import { validateLoadedPackage } from '@/components/project/themes/contract'
import { resolveWorkspacePages, routeCapability } from '@/components/project/themes/workspaceCapabilities'
import { clearReviewScope } from '@/utils/resultReviewDrafts'

const props = defineProps({ enabled: { type: Boolean, default: true } })
const route = useRoute()
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
const selection = shallowRef(null), themeError = ref(''), themeLoading = ref(false), themeDenied = ref(false)
let themeSequence = 0
const pack = computed(() => selection.value?.state === 'ready' ? selection.value.package : null)
const pages = computed(() => resolveWorkspacePages(pack.value))
const activePage = computed(() => pages.value.find(page => page.capability === routeCapability(route.name)))
const activeCapability = computed(() => routeCapability(route.name))
const icons = { overview: LayoutDashboard, blueprints: BookOpen, topics: MessageSquare, plans: Workflow, work: ListChecks, inspection: Activity, files: Files, agents: Bot, settings: Settings }
const themeContext = computed(() => ({ selection: selection.value, package: pack.value, loading: themeLoading.value, error: themeError.value, reload: loadTheme }))
provide('projectThemeContext', themeContext)
provide('projectAccessLost', () => { themeSequence++; themeDenied.value = true; themeLoading.value = false; selection.value = null; clearReviewScope(user.uid, projectId.value) })
async function loadTheme() {
  const request = ++themeSequence, id = projectId.value, owner = user.uid
  themeError.value = ''; themeLoading.value = true; themeDenied.value = false
  if (!id || !props.enabled) { themeLoading.value = false; return }
  try {
    const result = await projectThemeApi.binding(id)
    if (request !== themeSequence || id !== projectId.value || owner !== user.uid) return
    if (result.state === 'ready') result.package = validateLoadedPackage(result.package)
    selection.value = result
    if (result.state !== 'ready') themeError.value = result.error?.message || '尚未绑定主题版本'
  } catch (cause) { if (request === themeSequence) { themeError.value = cause.message || '主题读取失败'; themeDenied.value = [401,403,404].includes(cause?.status || cause?.response?.status) } }
  finally { if (request === themeSequence) themeLoading.value = false }
}
watch(() => [projectId.value, user.uid, props.enabled], () => { selection.value = null; loadTheme() }, { immediate: true })
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
  <section class="project-space" :class="{ 'project-collapsed': collapsed, 'project-mobile-open': mobileOpen, 'platform-page': !props.enabled, 'workspace-compact': pack?.theme.density === 'compact', 'workspace-blue': pack?.theme.accent === 'blue', 'workspace-slate': pack?.theme.accent === 'slate', 'workspace-reading': activePage?.layout === 'reading' }">
    <header v-if="enabled" class="project-space-header">
      <button class="project-nav-toggle" type="button" aria-label="项目导航" :aria-expanded="narrow ? mobileOpen : !collapsed" @click="toggleNavigation"><PanelLeft :size="18" /></button>
      <span class="project-breadcrumb">项目空间 / {{ activePage?.title || '项目' }}</span>

    </header>
    <div v-if="enabled && !projects.hasLoaded && !projects.error" class="project-space-state" role="status">正在读取项目…</div>
    <div v-else-if="enabled && (projects.error || !project)" class="project-space-state" role="alert">
      <p>{{ projects.error || '项目不存在或已无权访问' }}</p><a-button @click="refresh">重试</a-button>
    </div>
    <div v-if="enabled && themeDenied" class="project-space-state" role="alert">项目不可访问。<RouterLink :to="{name:'ProjectsComp'}">返回项目列表</RouterLink></div>
    <div v-if="enabled && project && !themeDenied && !themeLoading && (themeError || !pack?.theme.baseVersion)" class="project-theme-notice" role="status">{{ themeError ? `主题状态：${themeError}。当前使用内置完整基础界面，原绑定保留。` : '当前版本保留原展示页；业务办理继承内置完整基础界面 v1，项目绑定未改变。' }}<button type="button" @click="loadTheme">重新读取</button></div>
    <div v-if="enabled && project && themeLoading" class="project-space-state" role="status">正在读取项目主题…</div>
    <div class="project-space-body">
      <nav v-if="enabled && project && !themeDenied" class="project-navigation" aria-label="项目工作空间导航">
        <div class="project-head"><div class="project-head-tools"><span>项目空间</span><button type="button" aria-label="收起项目导航" @click="toggleNavigation"><PanelLeft :size="16" /></button></div><h2>{{ project?.name }}</h2><p class="project-description" :title="project?.description || ''">{{ project?.description || '暂无项目描述' }}</p></div>
        <template v-for="(item,index) in pages" :key="item.id">
          <small v-if="index === 0 || pages[index - 1].group !== item.group" class="project-nav-group">{{ item.group }}</small>
          <RouterLink :to="{ name: item.route, params: { project_id: projectId }, query: { theme_page: item.id } }" :class="{ active: activeCapability === item.capability }" :aria-current="activeCapability === item.capability ? 'page' : undefined"><component :is="icons[item.capability]" :size="18" />{{ item.title }}<span v-if="item.inherited" class="inherited-marker" title="继承完整基础界面 v1" aria-label="继承完整基础界面 v1">基础</span></RouterLink>
        </template>
        <RouterLink v-for="page in (pack?.theme.pages || []).filter(page => !page.capability)" :key="`extra-${page.id}`" :to="{name:'ProjectThemeDisplay', params:{project_id:projectId},query:{theme_page:page.id}}">{{ page.title }}</RouterLink>
        <small v-if="pack" class="project-nav-group">{{ selection.source?.name || pack.theme.name }} · {{ selection.version?.version || pack.theme.version }}</small>
        <RouterLink :to="{ name: 'ProjectsComp' }"><ArrowLeft :size="18" />项目列表</RouterLink>
      </nav>
      <div v-if="!enabled || project && !themeDenied" class="project-page"><slot /></div>
    </div>
  </section>
</template>

<style scoped lang="less">
.inherited-marker { margin-left: auto; font-size: 10px; color: var(--color-text-secondary); }
.project-space { height: 100%; display: flex; flex-direction: column; min-width: 0; background: var(--gray-25); }
.project-space-header { display: flex; gap: 12px; align-items: center; padding: 8px 16px; border-bottom: 1px solid var(--gray-150); min-height: 48px; flex-wrap: wrap; strong { overflow-wrap: anywhere; } select { max-width: 240px; min-width: 0; background: var(--gray-0); color: var(--color-text); border: 1px solid var(--gray-200); border-radius: 6px; padding: 6px; margin-left: auto; } }
.project-nav-toggle { display: grid; place-items: center; border: 1px solid var(--gray-150); border-radius: 6px; background: var(--gray-0); color: var(--color-text); min-height: 36px; min-width: 36px; cursor: pointer; }
.project-space-body { display: flex; flex: 1; min-height: 0; min-width: 0; }
.project-navigation { width: 220px; flex: 0 0 220px; background: var(--gray-0); border-right: 1px solid var(--gray-150); padding: 28px 15px; overflow-y: auto; a { display: flex; align-items: center; gap: 8px; min-height: 44px; padding: 10px; border-radius: 6px; color: var(--color-text); text-decoration: none; } a:hover, a.active { background: var(--main-10); color: var(--main-color); } p { font-size: 12px; color: var(--color-text-secondary); line-height: 1.7; margin-top: 24px; } }
.project-page :deep(a:not([class*="ant-"]):not(.object-target)) { color: var(--main-color); }
.project-page :deep(a:focus-visible) { outline: 2px solid var(--main-color); outline-offset: 3px; }
.project-page { flex: 1; min-width: 0; overflow: auto; > :deep(*) { min-width: 0; } }
.project-collapsed .project-navigation { display: none; }
.project-space-state { padding: 24px; }
.project-nav-group { display:block; padding:16px 10px 6px; color:var(--color-text-secondary); font-size:11px; letter-spacing:1px; overflow-wrap:anywhere; }
.project-theme-notice { padding:8px 16px; background:var(--gray-50); color:var(--color-text-secondary); font-size:12px; button { margin-left:8px; border:0; background:transparent; color:var(--main-color); cursor:pointer; } }
.workspace-reading .project-page > :deep(*) { max-width:1480px; margin-left:auto; margin-right:auto; }
.workspace-blue { --main-color:var(--color-info-700); --main-10:var(--color-info-50); }
.workspace-slate { --main-color:var(--gray-700); --main-10:var(--gray-100); }
.workspace-compact { --workspace-gap:16px; }
.workspace-compact .project-navigation a { min-height:36px; padding:6px 10px; }
.platform-page { background: transparent; }

button:focus-visible, a:focus-visible, select:focus-visible { outline: 2px solid var(--main-color); outline-offset: 2px; }
@media (max-width:700px) { .project-space-header { gap: 8px; padding: 8px; select { max-width: 180px; } } .project-nav-toggle { min-width: 44px; min-height: 44px; } .project-space-body { flex-direction: column; } .project-navigation { display: none; width: 100%; flex: 0 0 auto; max-height: 45vh; } .project-mobile-open .project-navigation { display: block; } }

.project-space { --main-color:#0f766e; --main-10:#eaf5f1; --gray-25:#f5f6f5; --gray-150:#e1e6e3; --color-text:#24312f; --color-text-secondary:#596961; }
:global(html.dark .project-space) { --main-color:#6dd6c4; --main-10:#253e35; --gray-25:#151d1b; --gray-0:#1e2825; --gray-150:#3d4b44; --color-text:#edf2ee; --color-text-secondary:#b2c0b7; }
.project-space.workspace-blue { --main-color:#365ac2; --main-10:#edf1fd; }:global(html.dark .project-space.workspace-blue) { --main-color:#aac0ff; --main-10:#29344b; }
.project-head { padding:0 11px 23px; >span { font-size:12px; letter-spacing:.8px; color:var(--color-text-secondary); } h2 { margin:8px 0 0; font-size:17px; font-weight:650; line-height:1.6; overflow-wrap:anywhere; } p { margin:3px 0 0; padding:0; font-size:12px; } }
.project-breadcrumb { font-size:12px; color:var(--color-text-secondary); }
@media(max-width:1100px) and (min-width:701px) { .project-navigation { width:190px; flex-basis:190px; } }

@media(min-width:701px) { .project-space-header { display:none; }.project-collapsed .project-space-header { display:flex; } }
.project-head-tools { display:flex; align-items:center; justify-content:space-between; font-size:12px; color:var(--color-text-secondary); button { border:0; background:none; color:inherit; cursor:pointer; } }
.project-head .project-description { display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; overflow-wrap:anywhere; max-width:100%; max-height:3.4em; margin-top:6px; line-height:1.7; }
.project-head select { margin-top:12px; max-width:100%; background:transparent; border:0; padding:0; color:var(--color-text-secondary); font-size:11px; }
.workspace-compact .project-page :deep(.overview-panel) { padding:19px; }.workspace-compact .project-page :deep(.attention-row), .workspace-compact .project-page :deep(.topic-directory-row) { padding-top:10px; padding-bottom:10px; }.workspace-compact .project-page :deep(.plan-card) { padding:18px 20px; }.workspace-compact .project-page :deep(.history-event:not(.discussion-event):not(.work-event)) { padding-top:1px; padding-bottom:1px; }.workspace-compact .project-page :deep(.tasks-table td) { padding-top:11px; padding-bottom:11px; }
.project-page :deep(.ant-btn-primary) { background:var(--main-color); border-color:var(--main-color); }
</style>
