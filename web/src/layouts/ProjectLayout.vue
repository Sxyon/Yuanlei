<script setup>
import { computed, provide, ref, shallowRef, watch, onMounted, onUnmounted, onErrorCaptured } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { LayoutDashboard, BookOpen, MessageSquare, Workflow, ListChecks, Bot, Files, Settings, Activity, PanelLeft, ArrowLeft } from '@lucide/vue'
import { useProjectsStore } from '@/stores/projects'
import { useChatUIStore } from '@/stores/chatUI'
import { useUserStore } from '@/stores/user'
import { projectThemeApi } from '@/apis/project_theme_api'
import { validateLoadedPackage } from '@/components/project/themes/contract'
import { resolveWorkspacePages, routeCapability, legacyThemeTarget } from '@/components/project/themes/workspaceCapabilities'
import { Modal } from 'ant-design-vue'
import { clearGovernanceDrafts } from '@/utils/governanceDrafts'
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
const selection = shallowRef(null), themeError = ref(''), themeLoading = ref(false), themeDenied = ref(false)
let themeSequence = 0
const fallback = ref(false), renderFailed = ref(false), renderError = ref('')
onErrorCaptured((cause, instance, info) => {
  if (!props.enabled || !['render function', 'setup function', 'https://vuejs.org/error-reference/#runtime-0', 'https://vuejs.org/error-reference/#runtime-1'].includes(info)) return
  renderFailed.value = true
  renderError.value = (selection.value?.binding ? '已保存，加载失败：' : '项目页面加载失败：') + cause.message
  return false
})
const pack = computed(() => !fallback.value && selection.value?.state === 'ready' ? selection.value.package : null)
const pages = computed(() => resolveWorkspacePages(pack.value))
const activePage = computed(() => pages.value.find(page => page.capability === routeCapability(route.name)))
const activeCapability = computed(() => routeCapability(route.name))
const icons = { overview: LayoutDashboard, blueprints: BookOpen, topics: MessageSquare, plans: Workflow, work: ListChecks, inspection: Activity, files: Files, agents: Bot, settings: Settings }
const editors = new Set(), pendingTheme = shallowRef(null)
let editPrompt = null
const themeScope = computed(() => props.enabled ? JSON.stringify([user.uid,projectId.value,selection.value?.binding?.version_id || '',selection.value?.generation || 0,fallback.value]) : String(user.uid))
provide('registerProjectThemeEdit', editor => { editors.add(editor); return () => editors.delete(editor) })
async function beforeSwitch(exclude = null) {
  const active = [...editors].filter(editor => editor !== exclude && editor.projectId() === projectId.value)
  if (active.some(editor => editor.busy())) { themeError.value = '当前业务操作正在提交，请完成后再切换。'; return false }
  const changed = active.filter(editor => editor.dirty())
  if (!changed.length) return true
  if (!editPrompt) editPrompt = new Promise(resolve => Modal.confirm({
    title:'当前项目有未保存内容', content:changed.map(editor => editor.label).join('、'),
    okText:'放弃所列修改并继续', cancelText:'返回编辑',
    onOk:() => { for (const editor of changed) editor.discard(); resolve(true) }, onCancel:() => resolve(false)
  })).finally(() => {editPrompt = null})
  return editPrompt
}
const themeContext = computed(() => ({ selection:selection.value, package:pack.value, loading:themeLoading.value, error:themeError.value, scope:themeScope.value, reload:loadTheme, apply:applyTheme, beforeSwitch }))
provide('projectThemeContext', themeContext)
function denyProject() {
  themeSequence++; themeDenied.value = true; themeLoading.value = false; selection.value = null; pendingTheme.value = null
  clearReviewScope(user.uid,projectId.value); clearGovernanceDrafts(user.uid,projectId.value)
}
provide('projectAccessLost',denyProject)
/** 旧主题query不决定目标page；准确对象及历史定位沿稳定能力接续。 */
async function locateTheme(changed) {
  const query = { ...route.query }
  if (changed) delete query.theme_return
  if (!changed && route.name === 'ProjectThemeDisplay' && pack.value?.manifest.componentAbi === 1) return
  const exact = route.params.task_id || route.params.agent_slug || ['topic_id','decision_id','comment_id','revision','decision_revision','blueprint','task_id','open'].some(key => query[key]) || (route.name === 'ProjectPlans' && /^#(?:task-|legacy-execution-)/.test(route.hash))
  const legacy = route.name === 'ProjectThemeDisplay' ? legacyThemeTarget(pack.value,route) : null
  if (legacy && (!changed || exact)) {
    if (changed) delete legacy.query.theme_return
    await router.replace(legacy);return
  }
  const currentCapability = routeCapability(route.name) || (query.topic_id || query.decision_id || query.comment_id || query.revision ? 'topics' : query.blueprint ? 'blueprints' : null)
  const capability = changed && !exact ? 'overview' : currentCapability
  const page = pages.value.find(item => item.capability === capability)
  if (!page) {
    if (route.name === 'ProjectThemeDisplay' && pack.value?.theme.pages.some(item => item.id === query.theme_page && !item.capability)) return
    const home = pages.value.find(item => item.capability === 'overview')
    await router.replace({name:home.route,params:{project_id:projectId.value},query:{theme_page:home.id}})
    return
  }
  query.theme_page = page.id
  if (changed && !exact) {
    await router.replace({name:page.route,params:{project_id:projectId.value},query:{theme_page:page.id}})
  } else if (route.name === 'ProjectThemeDisplay' || route.query.theme_page !== page.id || (changed && route.query.theme_return)) {
    await router.replace({name:route.name === 'ProjectThemeDisplay' ? page.route : route.name,params:{...route.params},query,hash:route.hash})
  }
}
async function applyTheme(result) {
  themeSequence++
  const changed = Boolean(selection.value && (selection.value.generation !== result.generation || selection.value.binding?.version_id !== result.binding?.version_id))
  if (result.state === 'ready') {
    try { result.package = validateLoadedPackage(result.package) }
    catch (cause) { result = {...result,state:'error',package:null,error:{message:cause.message}} }
  }
  selection.value = result; fallback.value = result.state !== 'ready'; pendingTheme.value = null; themeLoading.value = false
  themeError.value = result.state === 'ready' ? '' : (result.binding ? '已保存，加载失败：' : '') + (result.error?.message || '尚未绑定主题')
  if (changed) sessionStorage.removeItem('project-theme-return')
  await locateTheme(changed)
}
async function loadTheme() {
  const request = ++themeSequence, id = projectId.value, owner = user.uid
  if (!id || !props.enabled || themeDenied.value) return
  themeLoading.value = true; renderFailed.value = false; renderError.value = ''
  try {
    let result = await projectThemeApi.binding(id)
    if (result.state === 'ready') {
      try {result.package=validateLoadedPackage(result.package)}
      catch(cause){result={...result,state:'error',package:null,error:{message:cause.message}}}
    }
    if (request !== themeSequence || id !== projectId.value || owner !== user.uid) return
    const changed = selection.value && (selection.value.generation !== result.generation || selection.value.binding?.version_id !== result.binding?.version_id || selection.value.state !== result.state)
    if (changed && !await beforeSwitch()) {
      pendingTheme.value = result; themeError.value = '另一窗口已改变选择。当前保留旧版编辑，处理本地草稿后重新核对。'; return
    }
    if (request !== themeSequence) return
    await applyTheme(result)
  } catch (cause) {
    if (request !== themeSequence) return
    if ([401,403,404].includes(cause.status || cause.response?.status)) denyProject()
    else themeError.value = '绑定核实失败，当前仅为上次读取的界面：' + (cause.message || '请重试')
  } finally { if (request === themeSequence || !pendingTheme.value) themeLoading.value = false }
}
function onFocus() { if (document.visibilityState !== 'hidden') void loadTheme() }
onMounted(() => { window.addEventListener('focus',onFocus); document.addEventListener('visibilitychange',onFocus) })
onUnmounted(() => { themeSequence++; window.removeEventListener('focus',onFocus); document.removeEventListener('visibilitychange',onFocus) })
watch(() => [projectId.value, user.uid, props.enabled], () => { selection.value = null; themeDenied.value = false; fallback.value = false; void loadTheme() }, { immediate: true })
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
  <section class="project-space" :data-theme-version="selection?.binding?.version_id || ''" :data-theme-generation="selection?.generation || 0" :data-theme-scope="themeScope" :class="{ 'project-collapsed': collapsed, 'project-mobile-open': mobileOpen, 'platform-page': !props.enabled, 'workspace-compact': pack?.theme.density === 'compact', 'workspace-blue': pack?.theme.accent === 'blue', 'workspace-slate': pack?.theme.accent === 'slate', 'workspace-reading': activePage?.layout === 'reading' }">
    <header v-if="enabled" class="project-space-header">
      <button class="project-nav-toggle" type="button" aria-label="项目导航" :aria-expanded="narrow ? mobileOpen : !collapsed" @click="toggleNavigation"><PanelLeft :size="18" /></button>
      <span class="project-breadcrumb">项目空间 / {{ activePage?.title || '项目' }}</span>

    </header>
    <div v-if="enabled && !projects.hasLoaded && !projects.error" class="project-space-state" role="status">正在读取项目…</div>
    <div v-else-if="enabled && (projects.error || !project)" class="project-space-state" role="alert">
      <p>{{ projects.error || '项目不存在或已无权访问' }}</p><a-button @click="refresh">重试</a-button>
    </div>
    <div v-if="enabled && themeDenied" class="project-space-state" role="alert">项目不可访问。<RouterLink :to="{name:'ProjectsComp'}">返回项目列表</RouterLink></div>
    <div v-if="enabled && project && !themeDenied && (themeError || renderError || fallback || !pack?.theme.baseVersion)" class="project-theme-notice" role="status">
      {{ renderError || themeError || '当前版本的业务能力继承基础界面 v1。' }}
      <strong v-if="fallback">正在使用应急基础界面；持久选择未改变。</strong>
      <button type="button" @click="loadTheme">重新核对主题</button>
      <RouterLink :to="{name:'ProjectsComp',query:{tab:'themes',project_id:projectId,theme_action:'select'}}">选择／恢复主题</RouterLink>
    </div>
    <div v-if="enabled && project && themeLoading" class="project-space-state" role="status">正在读取项目主题…</div>
    <div class="project-space-body">
      <nav v-if="enabled && project && !themeDenied" class="project-navigation" aria-label="项目工作空间导航">
        <div class="project-head"><div class="project-head-tools"><span>项目空间</span><button type="button" aria-label="收起项目导航" @click="toggleNavigation"><PanelLeft :size="16" /></button></div><h2>{{ project?.name }}</h2><p class="project-description" :title="project?.description || ''">{{ project?.description || '暂无项目描述' }}</p></div>
        <template v-for="(item,index) in pages" :key="item.id">
          <small v-if="index === 0 || pages[index - 1].group !== item.group" class="project-nav-group">{{ item.group }}</small>
          <RouterLink :to="{ name: item.route, params: { project_id: projectId }, query: { theme_page: item.id } }" :class="{ active: activeCapability === item.capability }" :aria-current="activeCapability === item.capability ? 'page' : undefined"><component :is="icons[item.capability]" :size="18" />{{ item.title }}<span v-if="item.inherited" class="inherited-marker" title="继承完整基础界面 v1" aria-label="继承完整基础界面 v1">基础</span></RouterLink>
        </template>
        <RouterLink v-for="page in (pack?.theme.pages || []).filter(page => !page.capability)" :key="`extra-${page.id}`" :to="{name:'ProjectThemeDisplay', params:{project_id:projectId},query:{theme_page:page.id}}">{{ page.title }}</RouterLink>
        <small v-if="pack" class="project-nav-group">{{ themeError ? '上次读取：' : '' }}{{ selection.source?.name || pack.theme.name }} · {{ selection.version?.version || pack.theme.version }} · generation {{selection.generation}}</small>
        <RouterLink :to="{ name: 'ProjectsComp' }"><ArrowLeft :size="18" />项目列表</RouterLink>
      </nav>
      <div v-if="!enabled || project && !themeDenied" class="project-page"><slot v-if="!renderFailed" :theme-scope="themeScope" /></div>
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
