<script setup>
import { computed, nextTick, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useUserStore } from '@/stores/user'
import { createProjectThemeLoader, createProjectThemeAdapter } from '@/apis/project_theme_api'
import ThemeHost from './themes/ThemeHost.vue'
import { useRoute, useRouter } from 'vue-router'
import { readThemeReturn, saveThemeReturn } from '@/utils/projectThemeReturn'
import { legacyThemeTarget } from './themes/workspaceCapabilities'

const props = defineProps({ projectId: { type: String, required: true }, projectLabel: { type: String, default: '' } })
const route = useRoute(), router = useRouter()
const host = ref(null), refreshContext = shallowRef(null)
const restored = computed(() => refreshContext.value || readThemeReturn(route.query.theme_return, user.uid, props.projectId))
const user = useUserStore(), loading = ref(false), error = ref(''), selected = shallowRef(null)
let sequence = 0, controller
const adapter = computed(() => createProjectThemeAdapter(props.projectId, selected.value?.generation))
const manage = computed(() => ({ name: 'ProjectsComp', query: { tab: 'themes', project_id: props.projectId, theme_action: 'select' } }))
async function load() {
  const current = ++sequence, id = props.projectId
  const captured = host.value?.captureContext()
  refreshContext.value = captured?.projectId === id && captured?.userId === String(user.uid) ? captured : null
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''; selected.value = null
  if (!user.isLoggedIn) { loading.value = false; error.value = '登录已失效，请重新登录'; return }
  try {
    const value = await createProjectThemeLoader(id).load({ signal: controller.signal })
    if (current === sequence) {
      const target = legacyThemeTarget(value.selection?.package, route)
      if (target && value.selection?.state === 'ready') await router.replace(target)
      else selected.value = value.selection
    }
  }
  catch (cause) { if (current === sequence) { error.value = cause.message || '主题读取失败'; selected.value = cause.selection || null } }
  finally { if (current === sequence) loading.value = false }
}
watch(() => [props.projectId, user.uid, user.isLoggedIn], load, { immediate: true })
function openBusiness(event, context) {
  const token = saveThemeReturn(user.uid, context)
  const query = { theme_return: token }
  if (event.objectType === 'workTask') router.push({ name: 'ProjectWorkTaskView', params: { project_id: props.projectId, task_id: event.id }, query })
  else router.push({ name: 'ProjectTopics', params: { project_id: props.projectId }, query: { ...query, [event.objectType === 'topic' ? 'topic_id' : 'decision_id']: event.id }, hash: event.objectType === 'topic' ? '#topics' : '#decisions' })
}
watch(() => [host.value, route.query.theme_page], async () => { await nextTick(); if (host.value && route.query.theme_page && selected.value?.package.theme.pages.some(page => page.id === route.query.theme_page)) await host.value.navigate({kind:'page',pageId:String(route.query.theme_page)}) })
function invalidate(message) { sequence++; controller?.abort(); selected.value = null; error.value = message; loading.value = false }
onUnmounted(() => { sequence++; controller?.abort() })
</script>
<template>
  <section class="project-theme-panel">
    <div class="theme-status"><span>{{ selected?.version ? `${selected.source.name} · ${selected.version.version}` : '项目主题' }}<small v-if="selected?.generation"> · 选择修订 {{ selected.generation }}</small></span><div><RouterLink :to="manage">选择 / 更换主题</RouterLink><a-button size="small" :loading="loading" @click="load">重新读取</a-button></div></div>

    <div v-if="loading" role="status" class="theme-loading">正在读取准确版本…</div>
    <a-alert v-else-if="error || selected?.state !== 'ready'" type="warning" show-icon :message="error || selected?.error?.message || '尚未选择项目主题'" description="原项目绑定保留。可重试、显式选择其他版本，或进入当前基础界面及项目设置。"><template #action><RouterLink :to="manage">打开项目选择</RouterLink></template></a-alert>
    <ThemeHost v-else ref="host" :project-label="projectLabel" :theme-package="selected.package" :project-id="projectId" :user-id="String(user.uid)" :binding-generation="selected.generation" :adapter="adapter" :initial-context="restored" :open-business="openBusiness" @context-invalid="invalidate">
      <template #platform-navigation><RouterLink :to="{name:'ProjectDashboardComp',params:{project_id:projectId}}">项目总览</RouterLink><RouterLink :to="{name:'ProjectInspectionBoardComp',params:{project_id:projectId}}">议题</RouterLink><RouterLink :to="manage">主题管理与选择</RouterLink></template>
    </ThemeHost>
  </section>
</template>
<style scoped lang="less">
.project-theme-panel { display:flex; flex-direction:column; min-height:500px; min-width:0; gap:16px; .theme-host{min-height:500px;} }
.theme-status{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;>div{display:flex;gap:16px;align-items:center;}small{color:var(--color-text-secondary);}}
.theme-loading{padding:24px;}
</style>
