<script setup>
import { computed, inject, nextTick, ref, watch } from 'vue'
import { useUserStore } from '@/stores/user'
import { createProjectThemeAdapter } from '@/apis/project_theme_api'
import ThemeHost from './themes/ThemeHost.vue'
import { useRoute, useRouter } from 'vue-router'
import { readThemeReturn, saveThemeReturn } from '@/utils/projectThemeReturn'
const props = defineProps({ projectId: { type: String, required: true }, projectLabel: { type: String, default: '' } })
const route = useRoute(), router = useRouter(), user = useUserStore()
const context = inject('projectThemeContext'), host = ref(null)
const selected = computed(() => context.value.selection), loading = computed(() => context.value.loading), error = computed(() => context.value.error)
const restored = computed(() => readThemeReturn(route.query.theme_return,user.uid,props.projectId))
const adapter = computed(() => createProjectThemeAdapter(props.projectId,selected.value?.generation))
const manage = computed(() => ({ name:'ProjectsComp',query:{tab:'themes',project_id:props.projectId,theme_action:'select'} }))
const load = () => context.value.reload()
function openBusiness(event, value) {
  const token = saveThemeReturn(user.uid,value), query = {theme_return:token}
  if (event.objectType === 'workTask') router.push({name:'ProjectWorkTaskView',params:{project_id:props.projectId,task_id:event.id},query})
  else router.push({name:'ProjectTopics',params:{project_id:props.projectId},query:{...query,[event.objectType === 'topic' ? 'topic_id':'decision_id']:event.id}})
}
watch(() => [host.value,route.query.theme_page],async () => {await nextTick();if(host.value && selected.value?.package.theme.pages.some(page=>page.id===route.query.theme_page)) await host.value.navigate({kind:'page',pageId:String(route.query.theme_page)})})
function invalidate() { void load() }
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
