<script setup>
import { computed, inject, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { onBeforeRouteLeave, useRouter } from 'vue-router'
import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { supportsWorkspacePreview, themePreviewTarget } from '@/utils/projectThemePreview'
import { Modal } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'
import { projectThemeApi } from '@/apis/project_theme_api'
import { validateLoadedPackage } from './themes/contract'
import { createSyntheticAdapter } from './themes/syntheticAdapter'
import ThemeHost from './themes/ThemeHost.vue'

const props = defineProps({ projectId: { type: String, required: true }, projects: { type: Array, required: true }, stayInProject: Boolean, embedded: Boolean, initialVersionId: { type: String, default: '' } })
const emit = defineEmits(['project', 'cancel', 'selected'])
const router = useRouter(), user = useUserStore(), context = inject('projectThemeContext', null)
const loading = ref(false), saving = ref(false), checking = ref(false), error = ref(''), notice = ref(''), preview = ref(false)
const catalog = ref([]), current = shallowRef(null), versionId = ref(''), bundle = shallowRef(null), files = ref({}), condition = shallowRef(null)
const pending = shallowRef(null), committed = ref(false)
let sequence = 0, versionSequence = 0, checkSequence = 0, bindingSequence = 0, timer
const project = computed(() => props.projects.find(item => item.id === props.projectId))
const versions = computed(() => catalog.value.filter(source => source.status === 'active').flatMap(source => source.versions.map(version => ({ ...version, source }))))
const target = computed(() => versions.value.find(item => item.id === versionId.value))
const groups = computed(() => ['builtin','personal','project'].map(kind => ({ label: { builtin:'内置',personal:'个人公共',project:'项目专属' }[kind], options: versions.value.filter(v => v.source.kind === kind).map(v => ({ value:v.id, label:`${v.source.name} · ${v.version}${v.component_abi === 1 ? ' · ABI1只读展示／基础继承' : ''}${v.source.status !== 'active' ? ' · '+(v.source.status === 'disabled' ? '已停用，不可新选择' : '安全撤回，不可加载') : ''}`, disabled:v.source.status !== 'active' })) })))
const currentLabel = computed(() => current.value?.source ? `${current.value.source.name} · ${current.value.version.version}` : current.value?.binding ? `原选择 ${current.value.binding.version_id}` : '未绑定主题')
const aliases = computed(() => Object.entries(bundle.value?.manifest.files || {}))
const previewAdapter = computed(() => createSyntheticAdapter({ readAsset: ({alias,signal}) => projectThemeApi.asset({versionId:versionId.value,projectId:props.projectId,alias,signal}) }))
const sameFiles = (a,b) => Object.keys(a || {}).length === Object.keys(b || {}).length && Object.keys(a || {}).every(key => a[key] === b?.[key])
const dirty = computed(() => Boolean(props.projectId && versionId.value && (versionId.value !== current.value?.binding?.version_id || !sameFiles(files.value,current.value?.binding?.files))))
const ownEdit = useProjectThemeEdit('主题选择及文件映射', () => props.projectId, () => dirty.value, () => {versionId.value='';files.value={};bundle.value=null;condition.value=null}, () => saving.value || Boolean(pending.value))
function canDiscard() {
  if (saving.value || pending.value) return false
  if (!dirty.value) return true
  return new Promise(resolve => Modal.confirm({ title:'放弃本次未提交的主题选择及文件映射？', okText:'放弃并继续',cancelText:'返回编辑',onOk:()=>resolve(true),onCancel:()=>resolve(false) }))
}
async function changeProject(id) { if (await canDiscard()) emit('project',id || '') }
onBeforeRouteLeave(canDiscard)
function beforeUnload(event) {if(dirty.value || pending.value){event.preventDefault();event.returnValue=''}}
onMounted(()=>{window.addEventListener('beforeunload',beforeUnload);window.addEventListener('focus',onFocus);document.addEventListener('visibilitychange',onFocus)})
async function load() {
  const token = ++sequence, id = props.projectId
  versionSequence++; checkSequence++; clearTimeout(timer)
  loading.value = true; error.value = ''; notice.value = ''; current.value = null; bundle.value = null; catalog.value = []; condition.value = null; files.value = {}; versionId.value = ''; pending.value = null; committed.value = false
  try {
    const [directory, binding] = await Promise.all([projectThemeApi.catalog(id), id ? projectThemeApi.binding(id) : Promise.resolve(null)])
    if (token !== sequence) return
    catalog.value = directory.sources; current.value = binding
    if (props.initialVersionId) { versionId.value = props.initialVersionId; await chooseVersion() }
  } catch (cause) { if (token === sequence) error.value = cause.message }
  finally { if (token === sequence) loading.value = false }
}
/** 聚焦核对持久选择但保留当前草稿，旧条件必须重新确认。 */
async function refreshCurrent() {
  if (!props.projectId || loading.value || saving.value || checking.value || pending.value) return
  const token = sequence, request = ++bindingSequence
  try {
    const fresh = await projectThemeApi.binding(props.projectId)
    if (token !== sequence || request !== bindingSequence || saving.value || checking.value || pending.value) return
    if (fresh.generation !== current.value?.generation || fresh.binding?.version_id !== current.value?.binding?.version_id || fresh.state !== current.value?.state) {
      checkSequence++; checking.value = false
      current.value = fresh; condition.value = null; notice.value = ''
      error.value = '当前绑定已变化，已重新读取；本次选择及映射保留，请重新检查并确认。'
    }
  } catch(cause) {
    if (token !== sequence || request !== bindingSequence || saving.value || checking.value || pending.value) return
    checkSequence++; checking.value = false
    condition.value = null; notice.value = ''
    error.value = '当前绑定核实失败，原信息仅为上次读取：' + cause.message
  }
}
function onFocus() {if(document.visibilityState !== 'hidden')void refreshCurrent()}
async function refreshCatalog() {
  const token = sequence
  const result = await projectThemeApi.catalog(props.projectId)
  if (token === sequence) catalog.value = result.sources
}
async function chooseVersion() {
  const token = ++versionSequence, request = sequence, id = versionId.value, projectId = props.projectId
  checkSequence++; bundle.value = null; condition.value = null; files.value = {}; error.value = ''; notice.value = ''
  if (!id || !projectId) return
  try {
    const loaded = validateLoadedPackage(await projectThemeApi.version(id, projectId))
    if (token !== versionSequence || request !== sequence) return
    bundle.value = loaded
    files.value = Object.fromEntries(Object.keys(loaded.manifest.files).map(alias => [alias, current.value?.binding?.version_id === id ? current.value.binding.files[alias] || '' : '']))
    await checkConditions()
  } catch (cause) { if (token === versionSequence && request === sequence) error.value = cause.message }
}
async function checkConditions() {
  const token = ++checkSequence, request = sequence
  bindingSequence++
  condition.value = null
  if (!bundle.value || !current.value) return false
  checking.value = true
  try {
    const result = await projectThemeApi.check(props.projectId, {version_id:versionId.value, files:{...files.value}, expected_generation:current.value.generation})
    if (token !== checkSequence || request !== sequence) return false
    condition.value = result
    if (result.error?.code === 'binding_conflict') {
      const fresh = await projectThemeApi.binding(props.projectId)
      if (token !== checkSequence || request !== sequence) return false
      current.value = fresh; error.value = '选择冲突：已重新读取当前绑定，请重新检查并确认。'
    }
    return result.selectable
  } catch (cause) { if (token === checkSequence && request === sequence) error.value = cause.message; return false }
  finally { if (token === checkSequence) checking.value = false }
}
function filesChanged() { condition.value = null; checkSequence++; clearTimeout(timer); timer = setTimeout(checkConditions,250) }
async function finish(fresh) {
  current.value = fresh; pending.value = null
  if (fresh.state === 'ready') {
    try { fresh.package = validateLoadedPackage(fresh.package) }
    catch(cause) {fresh = {...fresh,state:'error',package:null,error:{message:cause.message}};current.value=fresh}
  }
  const ready = fresh.state === 'ready'
  notice.value = ready ? '选择已保存并核实；项目主题包可读。其他标签会在重新聚焦后核对。' : ''
  error.value = ready ? '' : `已保存，加载失败：${fresh.error?.message || '主题不可加载'}`
  saving.value = false
  if (props.stayInProject && context?.value) await context.value.apply(fresh)
  emit('selected',fresh)
}
async function reconcile() {
  const token = sequence, attempt = pending.value
  if (!attempt) return
  saving.value = true
  try {
    const fresh = await projectThemeApi.binding(props.projectId)
    if (token !== sequence) return
    const matches = fresh.binding?.version_id === attempt.version_id && sameFiles(fresh.binding.files,attempt.files)
    if (matches && fresh.generation > attempt.expected_generation) await finish(fresh)
    else {
      current.value = fresh; pending.value = null
      error.value = fresh.generation === attempt.expected_generation ? '核实后当前仍为原选择，请重新检查并确认。' : '另一窗口已更改选择，已重新读取；请重新检查并确认。'
      condition.value = null
      if (props.stayInProject) await context?.value?.reload()
    }
  } catch (cause) {
    if (token === sequence) error.value = committed.value ? `已保存，加载失败：${cause.message}；请重新读取核实。` : '保存结果待核实；请核实原项目绑定，暂不允许再次提交或更换目标。'
  } finally { if (token === sequence) saving.value = false }
}
async function save() {
  if (saving.value || pending.value) return
  const token = sequence, id = props.projectId
  bindingSequence++
  saving.value = true
  try {
    if (!await checkConditions() || token !== sequence) return
    if (props.stayInProject && context?.value && !await context.value.beforeSwitch(ownEdit)) return
    if (token !== sequence) return
    pending.value = {version_id:versionId.value, files:{...files.value}, expected_generation:current.value.generation}
    committed.value = false; error.value = ''; notice.value = ''
    await projectThemeApi.select(id,pending.value)
    if (token !== sequence) return
    committed.value = true
    await reconcile()
  } catch (cause) {
    if (token !== sequence) return
    const status = cause.status || cause.response?.status
    if (!pending.value) { error.value = cause.message; return }
    if (status >= 400 && status < 500 && status !== 409) { pending.value = null; error.value = cause.message; condition.value = null }
    else if (status === 409) {
      pending.value = null; condition.value = null
      try { current.value = await projectThemeApi.binding(id); error.value = '选择冲突：已回读另一窗口的选择，请重新检查并确认。' }
      catch { error.value = '选择冲突，当前绑定核实失败。请重新读取后确认。' }
    } else await reconcile()
  } finally { if (token === sequence) saving.value = false }
}

/** 真实能力预览另开临时项目页，选择草稿仍留在原弹窗。 */
function showPreview() {
  if (supportsWorkspacePreview(bundle.value)) {
    const target = router.resolve(themePreviewTarget(props.projectId, { versionId: versionId.value }))
    window.open(target.href, '_blank', 'noopener')
  } else preview.value = true
}
async function cancel() { if (await canDiscard()) emit('cancel') }
defineExpose({refreshCatalog, canDiscard})
watch(() => [props.projectId,user.uid,props.initialVersionId],load,{immediate:true})
onUnmounted(() => { window.removeEventListener('beforeunload',beforeUnload);window.removeEventListener('focus',onFocus);document.removeEventListener('visibilitychange',onFocus); sequence++;versionSequence++;checkSequence++;clearTimeout(timer) })
</script>
<template>
  <section class="theme-select" :data-project-id="projectId" :data-version-id="current?.binding?.version_id || ''" :data-generation="current?.generation">
    <div v-if="!embedded" class="toolbar"><h2>项目主题选择</h2><a-button :disabled="saving || !!pending" @click="cancel">取消</a-button></div>
    <a-alert v-if="error" type="error" role="alert" :message="error" />
    <a-alert v-if="notice" type="success" role="status" :message="notice" />
    <div v-if="pending" class="actions"><a-button :loading="saving" @click="reconcile">核实已提交的项目选择</a-button></div>
    <div v-show="!preview" class="select-grid">
      <section class="panel"><h3>目标项目与当前选择</h3><p v-if="stayInProject">{{ project?.name }} · {{ projectId }}</p><label v-else>分配目标项目<a-select :value="projectId || undefined" :options="projects.map(p=>({value:p.id,label:p.name}))" placeholder="选择有权项目" aria-label="主题目标项目" :disabled="saving || !!pending" @change="changeProject" /></label>
        <p v-if="current">当前：{{currentLabel}} · generation {{current.generation}}</p><a-alert v-if="current?.error" type="warning" :message="current.error.message" description="原绑定保留。可在此显式选择有权版本恢复，不依赖项目设置页面。" />
        <label>准确发布版本<a-select :value="versionId || undefined" :options="groups" :disabled="loading || saving || !!pending || !projectId" placeholder="选择准确发布版本" aria-label="主题发布版本" @change="value=>{versionId=value;chooseVersion()}" /></label>
        <details class="help"><summary>选择说明</summary><p>发布新版本不会自动替换项目选择；预览不保存绑定。目标项目改变后，会重新核对权限与文件条件。</p></details>
      </section>
      <section class="panel"><h3>项目文件与条件</h3><p v-if="!bundle">选定目标和准确版本后，读取版本要求。</p><p v-else-if="!aliases.length">此版本没有项目文件要求。</p>
        <label v-for="[alias,type] in aliases" :key="alias">{{alias}} · {{type}}<small>已保存：{{current?.binding?.files?.[alias] || '无'}}</small><a-input v-model:value="files[alias]" :aria-label="`文件绑定 ${alias}`" :aria-invalid="condition?.error?.alias===alias" :disabled="saving || !!pending" placeholder="当前项目内路径，例如 /reports/data.json" @change="filesChanged" /><small v-if="condition?.error?.alias===alias" role="alert">{{condition.error.message}}</small></label>
        <a-alert v-if="condition && !condition.selectable" type="warning" :message="condition.error.message" /><p v-if="condition?.selectable" role="status">来源、准确版本及文件条件通过；应用时重新校验。</p>
        <a-button :loading="checking" :disabled="!bundle || saving || !!pending" @click="checkConditions">重新检查条件</a-button>
        <h3>确认应用</h3><p>目标项目：{{project?.name || '尚未选择'}}</p><p>拟用：{{target ? `${target.source.name} · ${target.version}` : versionId || '未选择'}}</p><p v-for="[alias] in aliases" :key="alias">{{alias}} → {{files[alias] || '尚未填写'}}</p>
        <p class="help">切换影响此项目已打开页面；平台无法代为处理其他标签未保存内容。业务权限、状态、历史和项目文件保持原语义。</p>
        <div class="actions"><a-button :disabled="!bundle || saving" @click="showPreview">预览此准确版本</a-button><a-button type="primary" :loading="saving" :disabled="!condition?.selectable || checking || !!pending" @click="save">应用主题</a-button></div>
        <RouterLink v-if="notice && !stayInProject" :to="{name:'ProjectDashboardComp',params:{project_id:projectId}}">进入项目（可选）</RouterLink>
        <details v-if="bundle"><summary>版本与包详情</summary><p>目标项目ID：{{projectId}}</p><p v-if="initialVersionId">版本行带入：{{initialVersionId}}</p><p>{{bundle.reference}} · SHA-256 {{bundle.digest}} · ABI{{bundle.manifest.componentAbi}}</p></details>
      </section>
    </div>
    <section v-if="preview && bundle"><a-button @click="preview=false">返回本次选择</a-button><p>隔离合成预览；不读取真实业务或文件内容，不写项目绑定。</p><ThemeHost :theme-package="bundle" project-id="selection-preview" :user-id="String(user.uid)" :adapter="previewAdapter" simulation /></section>
  </section>
</template>
<style scoped lang="less">
.toolbar{display:flex;justify-content:space-between;gap:16px;align-items:center;margin-bottom:24px;}h2{font-size:20px;}h3{font-size:16px;}.select-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;}.panel{padding:24px;border:1px solid var(--gray-150);border-radius:8px;min-width:0;}label{display:flex;flex-direction:column;gap:8px;margin:20px 0;}.help{font-size:12px;color:var(--color-text-secondary);line-height:1.8;}.actions{display:flex;gap:12px;flex-wrap:wrap;}@media(max-width:768px){.select-grid{grid-template-columns:1fr;}.panel{padding:16px;}}
</style>
