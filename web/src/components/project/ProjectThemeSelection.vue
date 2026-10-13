<script setup>
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { projectThemeApi } from '@/apis/project_theme_api'
import { validateLoadedPackage } from './themes/contract'

const props = defineProps({ projectId: { type: String, required: true }, projects: { type: Array, required: true } })
const emit = defineEmits(['project', 'preview', 'cancel'])
const user = useUserStore(), router = useRouter(), loading = ref(false), saving = ref(false), error = ref('')
const catalog = ref([]), current = shallowRef(null), versionId = ref(''), bundle = shallowRef(null), files = ref(Object.create(null))
let sequence = 0, versionSequence = 0, controller
const versions = computed(() => catalog.value.flatMap(source => source.versions.map(version => ({ ...version, source }))))
const choices = computed(() => versions.value.filter(version => version.source.status === 'active'))
const target = computed(() => choices.value.find(item => item.id === versionId.value))
const currentVersion = computed(() => versions.value.find(item => item.id === current.value?.binding?.version_id))
const aliases = computed(() => Object.entries(bundle.value?.manifest.files || {}))
async function load() {
  const token = ++sequence, id = props.projectId; versionSequence++
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''; catalog.value = []; current.value = null; versionId.value = ''; bundle.value = null; files.value = Object.create(null)
  if (!id) { loading.value = false; return }
  try {
    const [directory, binding] = await Promise.all([projectThemeApi.catalog(id), projectThemeApi.binding(id, controller.signal)])
    if (token !== sequence) return
    catalog.value = directory.sources; current.value = binding
  } catch (cause) { if (token === sequence) error.value = cause.message }
  finally { if (token === sequence) loading.value = false }
}
async function chooseVersion() {
  const token = ++versionSequence, id = versionId.value, project = props.projectId
  files.value = Object.create(null); bundle.value = null; error.value = ''
  if (!id) return
  try {
    const loaded = validateLoadedPackage(await projectThemeApi.version(id, project))
    if (token === versionSequence && project === props.projectId) bundle.value = loaded
  } catch (cause) { if (token === versionSequence) error.value = cause.message }
}
async function save() {
  const project = props.projectId, token = sequence
  saving.value = true; error.value = ''
  try {
    const result = await projectThemeApi.select(project, { version_id: versionId.value, files: { ...files.value }, expected_generation: current.value.generation })
    if (token !== sequence) return
    current.value = result
    await router.push({ name: 'ProjectDashboardComp', params: { project_id: project }, query: { view: 'theme' } })
  } catch (cause) {
    if (token !== sequence) return
    if (cause.status === 409 || cause.response?.status === 409) {
      const fresh = await projectThemeApi.binding(project)
      if (token !== sequence) return
      current.value = fresh
    }
    error.value = cause.message || '选择保存失败；原绑定保留'
  } finally { if (token === sequence) saving.value = false }
}
watch(() => [props.projectId, user.uid], load, { immediate: true })
watch(versionId, chooseVersion)
onUnmounted(() => { sequence++; versionSequence++; controller?.abort() })
</script>
<template>
  <section class="theme-select">
    <div class="toolbar"><h2>项目主题选择</h2><a-button @click="emit('cancel')">返回主题管理</a-button></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <div class="select-grid">
      <section class="panel"><h3>当前项目与选择</h3><label>项目<a-select :value="projectId || undefined" :options="projects.map(p=>({value:p.id,label:p.name}))" placeholder="选择项目" aria-label="主题目标项目" :disabled="saving" @change="value=>emit('project',value)" /></label><p v-if="current">当前：{{ currentVersion ? `${currentVersion.source.name} · ${currentVersion.version}` : current.binding ? '原选择版本无法加载' : '未选择' }} · 修订 {{ current.generation }}</p><a-alert v-if="current?.error" type="warning" :message="current.error.message" /><label>发布版本<a-select v-model:value="versionId" :options="choices.map(v=>({value:v.id,label:`${v.source.name} · ${v.version} · ${v.source.kind==='builtin'?'内置':v.source.kind==='personal'?'个人公共':'项目专属'}`}))" :disabled="loading || saving || !projectId" placeholder="选择准确发布版本" aria-label="主题发布版本" /></label><p class="help">目录及保存时都重新授权。修改候选不会自动改变此选择。</p></section>
      <section class="panel"><h3>项目文件映射</h3><p v-if="!bundle">选定版本后显示它要求的文件。</p><p v-else-if="!aliases.length">此版本没有项目文件要求。</p><label v-for="[alias,type] in aliases" :key="alias">{{ alias }} · {{ type }}<a-input v-model:value="files[alias]" :aria-label="`文件绑定 ${alias}`" :disabled="saving" placeholder="当前项目内路径，例如 /reports/data.json" /></label><p class="help">后端检查当前Project归属、逐段no-follow、普通文件、实际类型与容量。每次内容读取重新核对当前绑定与权限。</p><h3>确认选择</h3><p v-if="target">目标：{{ target.source.name }} · {{ target.version }}</p><p v-for="[alias] in aliases" :key="alias">{{ alias }} → {{ files[alias] || '尚未绑定' }}</p><div class="actions"><a-button :disabled="!bundle || saving" @click="emit('preview', {versionId, projectId})">隔离预览</a-button><a-button type="primary" :loading="saving" :disabled="!bundle || !current || aliases.some(([alias])=>!files[alias])" @click="save">保存项目选择</a-button></div><p class="help">只保存当前项目准确版本与映射，不代表真实业务已可用。</p></section>
    </div>
  </section>
</template>
<style scoped lang="less">
.toolbar{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px;}h2{font-size:20px;}h3{font-size:16px;}.select-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;}.panel{padding:24px;border:1px solid var(--gray-150);border-radius:8px;min-width:0;}label{display:flex;flex-direction:column;gap:8px;margin:20px 0;}.help{font-size:12px;color:var(--color-text-secondary);line-height:1.8;}.actions{display:flex;gap:12px;flex-wrap:wrap;}@media(max-width:768px){.select-grid{grid-template-columns:1fr;}.panel{padding:16px;}}
</style>
