<script setup>
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useUserStore } from '@/stores/user'
import { createProjectThemeLoader, createS04Adapter } from '@/apis/project_theme_api'
import ThemeHost from './themes/ThemeHost.vue'

const props = defineProps({ projectId: { type: String, required: true } })
const user = useUserStore(), loading = ref(false), error = ref(''), selected = shallowRef(null)
let sequence = 0, controller
const adapter = computed(() => createS04Adapter(props.projectId, selected.value?.generation))
const manage = computed(() => ({ name: 'ProjectsComp', query: { tab: 'themes', project_id: props.projectId, theme_action: 'select' } }))
async function load() {
  const current = ++sequence, id = props.projectId
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''; selected.value = null
  try { const value = await createProjectThemeLoader(id).load({ signal: controller.signal }); if (current === sequence) selected.value = value.selection }
  catch (cause) { if (current === sequence) { error.value = cause.message || '主题读取失败'; selected.value = cause.selection || null } }
  finally { if (current === sequence) loading.value = false }
}
watch(() => [props.projectId, user.uid], load, { immediate: true })
onUnmounted(() => { sequence++; controller?.abort() })
</script>
<template>
  <section class="project-theme-panel">
    <div class="theme-status"><span>{{ selected?.version ? `${selected.source.name} · ${selected.version.version}` : '项目主题' }}<small v-if="selected?.generation"> · 选择修订 {{ selected.generation }}</small></span><div><RouterLink :to="manage">选择 / 更换主题</RouterLink><a-button size="small" :loading="loading" @click="load">重新读取</a-button></div></div>
    <a-alert type="info" show-icon message="S04：定义、包内资源及项目选择真实读取；业务数据和项目文件内容待 S05 接通。" />
    <div v-if="loading" role="status" class="theme-loading">正在读取准确版本…</div>
    <a-alert v-else-if="error || selected?.state !== 'ready'" type="warning" show-icon :message="error || selected?.error?.message || '尚未选择项目主题'" description="原项目绑定保留。可重试、显式选择其他版本，或进入原项目概览、工作台和资料。"><template #action><RouterLink :to="manage">打开项目选择</RouterLink></template></a-alert>
    <ThemeHost v-else :theme-package="selected.package" :project-id="projectId" :user-id="String(user.uid)" :binding-generation="selected.generation" :adapter="adapter">
      <template #platform-navigation><RouterLink :to="{name:'ProjectDashboardComp',params:{project_id:projectId}}">原项目概览</RouterLink><RouterLink :to="{name:'ProjectInspectionBoardComp',params:{project_id:projectId}}">项目工作台</RouterLink><RouterLink :to="manage">主题管理与选择</RouterLink></template>
    </ThemeHost>
  </section>
</template>
<style scoped lang="less">
.project-theme-panel { display:flex; flex-direction:column; min-height:500px; min-width:0; gap:16px; .theme-host{min-height:500px;} }
.theme-status{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap;>div{display:flex;gap:16px;align-items:center;}small{color:var(--color-text-secondary);}}
.theme-loading{padding:24px;}
</style>
