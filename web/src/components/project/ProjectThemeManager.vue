<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { History, CircleHelp } from '@lucide/vue'
import { supportsWorkspacePreview, themePreviewTarget } from '@/utils/projectThemePreview'
import { Modal } from 'ant-design-vue'
import { useUserStore } from '@/stores/user'
import { projectThemeApi } from '@/apis/project_theme_api'
import ProjectThemeSelection from './ProjectThemeSelection.vue'
import ThemeHost from './themes/ThemeHost.vue'
import { validateLoadedPackage } from './themes/contract'
import { createSyntheticAdapter } from './themes/syntheticAdapter'

const props = defineProps({ projectId: { type: String, default: '' }, projects: { type: Array, required: true }, stayInProject: Boolean })
const emit = defineEmits(['project', 'selected', 'catalog-changed'])
const route = useRoute(), router = useRouter(), user = useUserStore()
const sourceProjectId = ref(props.projectId), selectionVersionId = ref(String(route.query.theme_version || '')), selectionRef = ref(null)
const mode = ref('catalog'), scope = ref('builtin')
const selectionOpen = ref(route.query.theme_action === 'select'), previewProjectOpen = ref(false), previewProjectId = ref(''), workspacePreview = shallowRef(null)
const sources = ref([]), activeId = ref(''), candidate = shallowRef(null), definition = ref(''), error = ref(''), notice = ref(''), busy = ref(false)
const copyFrom = shallowRef(null), pendingCreate = shallowRef(null), createMatches = ref([])
const createOpen = ref(false), createName = ref(''), createKind = ref('personal'), operation = ref(''), reason = ref(''), audit = shallowRef(null), preview = shallowRef(null)
let generation = 0, catalogSequence = 0
const active = computed(() => sources.value.find(item => item.id === activeId.value))
const showHistory = ref(false)
const visible = computed(() => sources.value.filter(item => item.kind === scope.value && (showHistory.value || item.status === 'active')))
const historical = computed(() => sources.value.filter(item => item.kind === scope.value && item.status !== 'active').length)
const storageSummary = computed(() => {
  if (!audit.value) return '尚未检查。检查只读取主题包存储，不涉及项目业务或资料。'
  const files = audit.value.files, referenced = files.filter(item=>item.state==='referenced').length
  const residual = files.filter(item=>['orphan','temporary'].includes(item.state)).length
  const issues = files.filter(item=>!['referenced','orphan','temporary','removed_orphan','removed_temporary'].includes(item.state)).length
  return `已检查：${referenced} 个有效引用包，${residual} 项未引用残留，${issues} 项异常。${issues ? '请展开明细处理缺失或损坏。' : '引用包未发现异常。'}`
})
const mutable = computed(() => active.value && active.value.kind !== 'builtin')
const dirty = computed(() => {
  if (!candidate.value?.package) return false
  try { return JSON.stringify(JSON.parse(definition.value)) !== JSON.stringify({ manifest: candidate.value.package.manifest, theme: candidate.value.package.theme }) }
  catch { return true }
})
useProjectThemeEdit('主题编辑草稿', () => props.stayInProject ? props.projectId : '', () => dirty.value, () => {definition.value=JSON.stringify({manifest:candidate.value.package.manifest,theme:candidate.value.package.theme},null,2)}, () => busy.value)
const fileStateText = value => ({referenced:'已引用且字节有效',orphan:'完整未引用包',temporary:'临时残留',removed_orphan:'已清理未引用包',removed_temporary:'已清理临时残留',missing:'引用包缺失',package_missing:'引用包缺失',package_corrupt:'包字节损坏',unsafe_entry:'非普通文件，拒绝清理'}[value] || `校验失败：${value}`)
const statusText = value => ({ active: '可新选择', disabled: '已停用，既有选择可加载', withdrawn: '安全撤回，加载已拒绝' }[value])
async function canDiscard(includeSelection = true) {
  if (includeSelection && selectionRef.value && !await selectionRef.value.canDiscard()) return false
  if(!dirty.value) return true
  return new Promise(resolve => Modal.confirm({title:'放弃未保存的主题编辑草稿？',okText:'放弃并离开',cancelText:'继续编辑',onOk:()=>resolve(true),onCancel:()=>resolve(false)}))
}
onBeforeRouteLeave(() => canDiscard(false))
function beforeUnload(event) { if(dirty.value) { event.preventDefault(); event.returnValue='' } }
onMounted(() => { window.addEventListener('beforeunload',beforeUnload); window.addEventListener('focus',onFocus); document.addEventListener('visibilitychange',onFocus) })
/** 核对目录保留候选草稿与当前准确版本，不因自动刷新重建编辑状态。 */
async function refreshCatalog() {
  const token = generation, request = ++catalogSequence, id = sourceProjectId.value
  try {
    const result = await projectThemeApi.catalog(id)
    if (token === generation && request === catalogSequence) sources.value = result.sources
  } catch (cause) { if (token === generation && request === catalogSequence) throw cause }
}
function onFocus() {
  const token = generation
  if (document.visibilityState !== 'hidden' && !busy.value) void refreshCatalog().catch(cause => { if (token === generation) error.value = '目录核对失败：' + cause.message })
}
async function selected(value) {
  emit('selected',value)
  await run(refreshCatalog)
}
async function load() {
  const token = ++generation, request = ++catalogSequence, id = sourceProjectId.value
  busy.value = true; error.value = ''; sources.value = []; activeId.value = ''; candidate.value = null; preview.value = null; audit.value = null; operation.value = ''
  try { const result = await projectThemeApi.catalog(id); if (token === generation && request === catalogSequence) sources.value = result.sources }
  catch (cause) { if (token === generation && request === catalogSequence) error.value = cause.message }
  finally { if (token === generation && request === catalogSequence) busy.value = false }
}
async function run(action) {
  const token = generation
  catalogSequence++
  busy.value = true; error.value = ''; notice.value = ''
  try { await action(token); if (token === generation) await refreshCatalog() } catch (cause) { if (token === generation) error.value = (cause.message || '操作失败；原选择保留') + (cause.response?.data?.detail?.code==='version_conflict' ? '。请回到编辑草稿修改 theme.version，再保存校验并发布。' : '') }
  finally { if (token === generation) busy.value = false }
}
async function openSource(source, confirmed = false) {
  if(!confirmed && !await canDiscard()) return false
  const token = ++generation; activeId.value = source.id; candidate.value = null; audit.value = null; preview.value = null; operation.value = ''; notice.value = ''; error.value = ''
  mode.value = source.kind === 'builtin' ? 'versions' : 'candidate'
  if (source.kind === 'builtin') { await run(async () => {}); return true }
  await run(async () => {
    const result = await projectThemeApi.candidate(source.id, sourceProjectId.value)
    if (token !== generation || activeId.value !== source.id) return
    candidate.value = result; definition.value = result.package ? JSON.stringify({ manifest: result.package.manifest, theme: result.package.theme }, null, 2) : ''
  })
  return activeId.value === source.id && Boolean(candidate.value)
}
async function upload(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file || !active.value || !await canDiscard()) return
  const source = active.value, revision = candidate.value?.source.candidate_revision || source.candidate_revision
  await run(async token => {
    const result = await projectThemeApi.upload(source.id, sourceProjectId.value, revision, file)
    if (token !== generation || activeId.value !== source.id) return
    candidate.value = result; Object.assign(source, result.source); definition.value = JSON.stringify({manifest:result.package.manifest,theme:result.package.theme},null,2)
    notice.value = '编辑草稿 ZIP 已保存并完成校验；尚未发布，不改变项目选择。'
  })
}
async function save(token) {
  const body = JSON.parse(definition.value), source = active.value
  const result = await projectThemeApi.edit(source.id, sourceProjectId.value, { ...body, expected_revision: candidate.value.source.candidate_revision })
  if (token !== generation || activeId.value !== source.id) return
  candidate.value = result; Object.assign(source, result.source); definition.value = JSON.stringify({ manifest: result.package.manifest, theme: result.package.theme }, null, 2); notice.value = '编辑草稿已保存并校验，旧发布版本与项目选择保留。'
}
async function publish(token) {
  if (dirty.value) throw new Error('编辑草稿存在未保存修改，请先保存并校验')
  const source = active.value
  const version = await projectThemeApi.publish(source.id, sourceProjectId.value, candidate.value.source.candidate_revision)
  if (token !== generation || activeId.value !== source.id) return
  source.versions = [version, ...source.versions.filter(item=>item.id!==version.id)]
  emit('catalog-changed')
  notice.value = `已发布 ${source.name} · ${version.version}；项目选择未改变。`; mode.value = 'versions'
}
/** 创建前显示准确出处；打开弹窗不产生身份。 */
function prepareCreate(version = null) {
  if (pendingCreate.value) return
  copyFrom.value = version ? {id:version.id,name:active.value.name,version:version.version,projectId:sourceProjectId.value} : null
  createName.value = version ? `${active.value.name}（副本）` : ''
  createKind.value = 'personal'; createOpen.value = true
}
/** 同模式不重读；草稿与发布列表之间保留本地编辑。 */
function showMode(next) { mode.value = next }
/** 核实成功后定位原草稿，不发布或分配。 */
async function locateCreated(source, recovered = false) {
  if (!await canDiscard()) return
  if (!sources.value.some(item=>item.id===source.id)) sources.value.push({...source,versions:[]})
  createOpen.value = false; scope.value = source.kind
  if (!await openSource(source, true)) return
  pendingCreate.value = null; createMatches.value = []
  notice.value = source.candidate_digest
    ? `${recovered ? '已核实副本' : '可编辑副本已创建'}“${source.name}”，已定位编辑草稿；尚未发布、尚未应用到项目。`
    : `主题身份“${source.name}”已建立，编辑草稿尚未完成；请在此主题上传完整 ZIP，不要重新创建副本。尚未发布、尚未应用。`
}
/** 请求不明先回读有权身份，绝不自动重发创建。 */
async function verifyCreate() {
  const pending = pendingCreate.value, token = generation
  if (!pending) return
  const result = await projectThemeApi.catalog(pending.body.kind==='project' ? pending.body.project_id : '')
  if (token !== generation || pendingCreate.value !== pending) return
  createMatches.value = result.sources.filter(item => !pending.beforeIds.includes(item.id) && item.kind===pending.body.kind && item.name===pending.body.name && (item.copied_from_version_id || null)===(pending.body.copy_version_id || null))
  if (createMatches.value.length===1) await locateCreated(createMatches.value[0], true)
  else if (!createMatches.value.length && pending.rejection) {
    pendingCreate.value = null
    error.value = `创建被拒绝，目录未发现新增副本：${pending.rejection}。请修正条件后再创建。`
  } else error.value = createMatches.value.length ? '发现多个同名新主题，请核对下列准确身份；未自动重发创建。' : '暂未查到可确认的新主题，创建结果仍不明。请重新核实，勿重复创建。'
}
/** 仅发送一次创建，异常进入有权目录核实。 */
async function create() {
  if (pendingCreate.value) throw new Error('上次创建结果尚未核实，请先核实已有结果。')
  if (!createName.value.trim()) throw new Error('请填写新主题名称。')
  if (!await canDiscard()) return
  if (dirty.value) definition.value = JSON.stringify({manifest:candidate.value.package.manifest,theme:candidate.value.package.theme},null,2)
  const token = generation, copy = copyFrom.value
  const body = {name:createName.value.trim(),kind:copy ? 'personal' : createKind.value,project_id:!copy && createKind.value==='project' ? sourceProjectId.value : null,copy_version_id:copy?.id || null,copy_project_id:copy ? copy.projectId || null : null}
  const before = await projectThemeApi.catalog(body.kind==='project' ? body.project_id : '')
  if (token !== generation) return
  pendingCreate.value = {body,beforeIds:before.sources.map(item=>item.id)}
  let result
  try { result = await projectThemeApi.create(body) }
  catch (cause) {
    if (token !== generation) return
    createOpen.value = false
    if (cause.status>=400 && cause.status<500) pendingCreate.value.rejection = cause.message
    error.value = `创建请求未完整返回：${cause.message}。正在核实是否已有主题身份。`
    try { await verifyCreate() }
    catch { if (token===generation) error.value = '创建结果及目录暂无法核实。保留了本次名称与准确出处，请重新核实；不要重复创建。' }
    return
  }
  if (token !== generation) return
  await locateCreated(result)
}
async function maintain() {
  const source = active.value, token = generation
  const result = await projectThemeApi.status(source.id, sourceProjectId.value, operation.value, reason.value)
  if (token !== generation) return
  Object.assign(source, result); emit('catalog-changed'); operation.value = ''; reason.value = ''; notice.value = '来源状态及原因已保存；原项目绑定保留。'
}
async function inspect(clean = false) {
  const source = active.value, token = generation
  const result = await (clean ? projectThemeApi.cleanup(source.id, sourceProjectId.value) : projectThemeApi.audit(source.id, sourceProjectId.value))
  if (token !== generation || source.id !== activeId.value) return
  audit.value = result
}
async function showPreview({versionId,projectId=sourceProjectId.value}={}) {
  if (!versionId && dirty.value) throw new Error('编辑草稿存在未保存修改，请先保存并校验')
  const token = generation, source = active.value
  let loaded, assetScope
  if (versionId) {
    loaded = await projectThemeApi.version(versionId, projectId)
    assetScope = { versionId, projectId }
  } else {
    if (!candidate.value?.package) return
    loaded = candidate.value.package
    assetScope = { sourceId: source.id, projectId, revision: candidate.value.source.candidate_revision }
  }
  const pack = validateLoadedPackage(loaded)
  if (token !== generation) return
  if (supportsWorkspacePreview(pack)) {
    workspacePreview.value = versionId ? { versionId } : { sourceId: source.id, revision: candidate.value.source.candidate_revision }
    previewProjectId.value = props.projects.some(item => item.id === projectId) ? projectId : ''
    if (previewProjectId.value) await enterWorkspacePreview()
    else previewProjectOpen.value = true
    return
  }
  const loader = { readAsset: ({alias,signal}) => projectThemeApi.asset({...assetScope,alias,signal}) }
  preview.value = { package: pack, adapter: createSyntheticAdapter(loader), returnMode: mode.value }
  mode.value = 'preview'
}
watch(() => [sourceProjectId.value, user.uid], () => load(), { immediate: true })
watch(() => user.uid, () => {pendingCreate.value=null;createMatches.value=[];copyFrom.value=null;createOpen.value=false})
watch(() => props.projectId, id => { if(props.stayInProject) sourceProjectId.value=id })
async function assignVersion(id = '') {
  if (!await canDiscard()) return
  selectionVersionId.value = id
  selectionOpen.value = true
}
/** 关闭前保护选择草稿，清除一次性打开意图。 */
async function closeSelection() {
  if (selectionRef.value && !await selectionRef.value.canDiscard()) return
  selectionOpen.value = false
  if (route.query.theme_action === 'select') {
    const query = {...route.query}; delete query.theme_action; delete query.theme_version
    await nextTick()
    await router.replace({name:route.name,params:route.params,query})
  }
}
/** 在有权项目中打开准确引用的只读页面。 */
async function enterWorkspacePreview() {
  if (!previewProjectId.value || !workspacePreview.value) return
  await router.push(themePreviewTarget(previewProjectId.value, workspacePreview.value))
}
async function changeSourceProject(id) {
  if (await canDiscard()) sourceProjectId.value = id || ''
}
async function changeTarget(id) {
  emit('project',id)
}
defineExpose({ canDiscard, openPreview: value => run(() => showPreview(value)), showCatalog: async () => { if(await canDiscard()) mode.value = 'catalog' } })
onUnmounted(() => { generation++; window.removeEventListener('beforeunload',beforeUnload); window.removeEventListener('focus',onFocus); document.removeEventListener('visibilitychange',onFocus) })
</script>
<template>
  <section class="theme-management">
    <section v-if="pendingCreate" class="creation-recovery" role="status"><strong>创建结果待核实：{{pendingCreate.body.name}}</strong><p>归属：{{pendingCreate.body.kind==='personal' ? '我的主题，仅本人项目复用' : '项目专属'}}；准确来源版本：{{pendingCreate.body.copy_version_id || '空白主题'}}。未核实前不再次创建。</p><a-button :disabled="busy" @click="run(verifyCreate)">重新核实创建结果</a-button><p v-for="source in createMatches" :key="source.id">{{source.name}} · {{source.id}}<a-button @click="run(()=>locateCreated(source,true))">打开此主题草稿</a-button></p></section>
    <a-alert v-if="error" type="error" show-icon :message="error" /><a-alert v-if="notice" type="success" show-icon :message="notice" />
    <template v-if="mode==='preview' && preview"><div class="toolbar"><a-button @click="mode=preview.returnMode;preview=null">返回维护 / 选择</a-button><p class="preview-notice">包定义及包内资源真实读取；业务及项目文件内容为合成预览，不保存项目选择。</p></div><ThemeHost :theme-package="preview.package" project-id="preview-market" project-label="隔离合成项目" :user-id="String(user.uid)" :adapter="preview.adapter" simulation /></template>
    <template v-else>
      <div class="toolbar"><div class="actions"><a-radio-group :disabled="busy" :value="scope" @change="async event=>{if(await canDiscard()){scope=event.target.value;mode='catalog';activeId='';candidate=null;definition='';await run(refreshCatalog)}}" :options="[{value:'builtin',label:'平台内置'},{value:'personal',label:'我的主题'},{value:'project',label:'项目专属'}]" /><a-select :value="sourceProjectId || undefined" :options="projects.map(p=>({value:p.id,label:p.name}))" placeholder="来源所属项目（非分配目标）" aria-label="主题来源所属项目" :disabled="busy || stayInProject || scope!=='project'" allow-clear @change="changeSourceProject" /></div><div class="actions"><a-button v-if="!stayInProject" :disabled="busy" @click="assignVersion()">项目主题设置</a-button><a-button type="primary" :disabled="busy || !!pendingCreate" @click="prepareCreate()">建立来源</a-button>    <a-popover trigger="click" title="主题使用与维护"><template #content><div class="help-content"><p>选择项目后可分配主题，也可从准确发布版本发起分配。成功后在本页核实结果。</p><p>编辑草稿用于修改；发布生成不可变版本；分配才改变项目选择。预览不保存选择，新发布不会自动替换项目版本。</p><p>我的主题仅供本人项目复用；项目专属仅限所属项目。停用版本保留历史及已有绑定，可在历史目录追溯。</p><p>目录随来源切换、创建、保存、发布、维护及分配操作自动核对；重新聚焦时也会核对。</p></div></template><a-button type="text" aria-label="主题管理帮助" title="主题管理帮助"><CircleHelp :size="18" /></a-button></a-popover>
</div></div>
      <div class="management-grid"><section class="panel"><header class="directory-heading"><h2>来源目录</h2><small v-if="scope==='personal'">仅供本人项目复用</small><a-button v-if="historical" type="text" aria-label="查看历史来源" :aria-pressed="showHistory" :title="showHistory ? '隐藏历史来源' : '查看历史来源'" @click="showHistory=!showHistory"><History :size="17" /></a-button></header><p v-if="showHistory" class="help">含 {{historical}} 个历史来源，停用版本保留追溯。</p><p v-if="busy && !sources.length" role="status">正在读取有权目录…</p><a-empty v-else-if="!visible.length" :description="scope==='project' && !sourceProjectId ? '先选择有权项目' : '暂无来源，可复制内置版本或建立来源'" /><button v-for="source in visible" :key="source.id" class="source" :disabled="busy" :aria-current="source.id===activeId ? 'true':undefined" @click="openSource(source)"><strong>{{source.name}}</strong><small>{{statusText(source.status)}} · {{source.versions.length}} 个版本</small></button></section>
      <section class="panel"><template v-if="active"><div class="toolbar"><div><h2>{{active.name}}</h2><p class="help">{{active.description ? `${active.description} · ` : ''}}{{statusText(active.status)}}</p></div><div class="actions"><a-button v-if="mutable" class="mode-choice" :class="{selected:mode==='candidate'}" :aria-pressed="mode==='candidate'" :disabled="busy" @click="showMode('candidate')">编辑草稿</a-button><a-button class="mode-choice" :class="{selected:mode==='versions'}" :aria-pressed="mode==='versions'" :disabled="busy" @click="showMode('versions')">已发布版本</a-button></div></div>
        <p v-if="!mutable" class="help">平台内置主题只读。可从准确已发布版本创建可编辑副本，修改后发布到我的主题。</p><p v-if="dirty && mode!=='candidate'" role="status">未保存修改保留在编辑草稿中。</p>
        <template v-if="mode==='candidate' && mutable"><h3>编辑草稿</h3><p>已保存草稿修订 {{candidate?.source.candidate_revision || 0}}；已发布版本保持原字节。</p><label class="upload">替换草稿 ZIP<input type="file" accept=".zip,application/zip" aria-label="上传草稿ZIP" :disabled="busy" @change="upload" /></label><label v-if="candidate?.package">manifest / theme 受控定义<a-textarea v-model:value="definition" :rows="18" :disabled="busy" aria-label="编辑草稿JSON定义" /></label><p v-else class="help">先上传草稿ZIP，或从内置版本复制完整包。</p><div class="actions"><a-button :disabled="busy" @click="openSource(active)">重新读取草稿</a-button><a-button :disabled="!candidate?.package || busy" @click="run(save)">保存并校验</a-button><a-button :disabled="!candidate?.package || dirty || busy" @click="run(()=>showPreview())">预览已保存草稿</a-button><a-popconfirm title="发布此已保存草稿的新版本？发布后仍需显式分配，项目当前选择不变。" @confirm="run(publish)"><a-button type="primary" :disabled="!candidate?.package || dirty || active.status!=='active' || busy">发布新版本</a-button></a-popconfirm></div><p v-if="dirty" role="status">编辑草稿存在未保存修改，请先保存并校验。</p><p class="help">编辑文本需先保存；预览及发布使用服务端已保存修订；修改 theme.version 设置新版本标识。manifest.files 是项目文件声明，manifest.assets 是包内素材；新素材通过完整 ZIP 提供。校验失败明确定位字段；新资源用完整ZIP替换。</p></template>
        <template v-if="mode==='versions'"><p v-if="!active.versions.length">尚无已发布版本。请在编辑草稿中保存校验，再发布新版本。</p><article v-for="version in active.versions" :key="version.id" class="version"><div><strong>{{active.name}} · {{version.version}}</strong><p class="help">{{version.created_at}} · {{version.size}} bytes · 发布者 {{version.created_by || '平台'}}</p><p class="help digest">版本 {{version.id}} · 草稿修订 {{version.candidate_revision}}</p><p class="help digest">SHA-256 {{version.digest}}</p></div><div class="actions"><a-button :disabled="busy || active.status==='withdrawn'" @click="run(()=>showPreview({versionId:version.id}))">预览版本</a-button><a-button :disabled="busy || !!pendingCreate || active.status==='withdrawn'" @click="prepareCreate(version)">创建可编辑副本</a-button><a-button :disabled="active.status!=='active'" @click="assignVersion(version.id)">分配到项目</a-button></div></article></template>
        <details v-if="mutable" class="maintenance" @toggle="event=>{if(event.target.open && !audit) run(()=>inspect())}"><summary>存储检查与维护</summary><p class="help">检查主题草稿与已发布 ZIP 的引用和字节，不是可视化配置或项目资料校对。检查不删除文件。</p><p role="status">{{storageSummary}}</p><div class="actions"><a-button :disabled="busy" @click="run(()=>inspect())">检查存储</a-button><a-popconfirm title="重新查询引用后，清理此主题未使用完整包与临时残留？被草稿或已发布版本引用的包保留。" @confirm="run(()=>inspect(true))"><a-button :disabled="busy || !audit">清理未引用残留</a-button></a-popconfirm></div><details v-if="audit"><summary>查看检查明细</summary><ul><li v-for="(item,index) in audit.files" :key="index">{{fileStateText(item.state)}} <span class="digest">{{item.digest}}</span></li></ul></details><details><summary>维护历史与部署恢复说明</summary><p v-for="(item,index) in audit?.history" :key="index">{{item.created_at}} · {{item.action}} · {{item.reason}} · {{item.actor_uid}}</p><p>部署维护者暂停写入后同时备份PG和主题文件，恢复到隔离环境逐版本与绑定核对；普通用户不持有数据库恢复权限。</p></details></details>
        <div v-if="mutable" class="maintenance"><h3>来源操作</h3><div class="actions"><a-button v-if="active.status==='active'" @click="operation='disabled';reason=''">停用来源</a-button><a-button v-if="active.status!=='withdrawn'" danger @click="operation='withdrawn';reason=''">安全撤回</a-button><a-button v-if="active.status!=='active'" @click="operation='active';reason=''">恢复来源</a-button></div><p class="help">停用停止新发布和新选择，既有版本继续加载；安全撤回阻止全部版本加载，原绑定及历史保留。</p><a-alert v-if="active.reason" type="warning" :message="active.reason" /></div>
      </template><a-empty v-else description="选择一个主题查看编辑草稿与已发布版本" /></section></div>
    </template>
    <a-modal :open="selectionOpen" title="项目主题设置" :footer="null" :width="1100" :mask-closable="false" :destroy-on-close="true" @cancel="closeSelection">
      <ProjectThemeSelection v-if="selectionOpen" ref="selectionRef" :project-id="projectId" :projects="projects" :initial-version-id="selectionVersionId" :stay-in-project="stayInProject" embedded @selected="selected" @project="changeTarget" @cancel="closeSelection" />
    </a-modal>
    <a-modal v-model:open="previewProjectOpen" title="选择预览项目" ok-text="开始只读预览" :ok-button-props="{disabled:!previewProjectId}" @ok="enterWorkspacePreview">
      <p>使用该项目有权读取的真实数据，在同一项目页面中查看准确版本效果。预览只读，不修改项目选择或业务。</p>
      <a-select v-model:value="previewProjectId" :options="projects.map(item=>({value:item.id,label:item.name}))" aria-label="主题预览项目" placeholder="选择有权项目" style="width:100%" />
      <p v-if="!projects.length">暂无有权项目，请先建立项目。</p>
    </a-modal>
    <a-modal v-model:open="createOpen" :title="copyFrom ? '创建可编辑副本' : '建立主题'" :mask-closable="false" :confirm-loading="busy" :ok-button-props="{disabled:!createName.trim() || !!pendingCreate}" ok-text="确认创建" @ok="run(create)"><label>新主题名称<a-input v-model:value="createName" :disabled="busy" :maxlength="160" aria-label="新主题名称" /></label><template v-if="copyFrom"><p>归属：我的主题，仅供本人项目复用。</p><p>准确来源：{{copyFrom.name}} · {{copyFrom.version}}</p><p class="digest">发布版本 ID：{{copyFrom.id}}</p></template><label v-else>归属<a-select v-model:value="createKind" :disabled="busy" :options="[{value:'personal',label:'我的主题，仅本人项目复用'},{value:'project',label:'当前项目专属',disabled:!sourceProjectId}]" /></label><p>创建后进入编辑草稿；尚未发布、尚未应用到项目。{{copyFrom ? '原主题及准确发布版本保持不变。' : '空白主题需上传完整 ZIP。'}}</p></a-modal>
    <a-modal :open="Boolean(operation)" title="确认来源操作" :confirm-loading="busy" @cancel="operation=''" @ok="run(maintain)"><p>来源：{{active?.name}}</p><p>{{operation==='disabled'?'停止新发布、新选择；既有绑定继续加载。':operation==='withdrawn'?'来源全部版本停止加载；所有已绑定项目保留原选择并显示原因。':'恢复来源使用；原项目版本与映射保留。'}}</p><label>原因（撤回及恢复撤回必填）<a-textarea v-model:value="reason" :maxlength="2000" /></label></a-modal>
  </section>
</template>
<style scoped lang="less">
.mode-choice.selected{border-color:var(--main-color);background:var(--main-10);color:var(--main-color);font-weight:600;}.creation-recovery{padding:16px;border:1px solid var(--gray-150);border-radius:8px;overflow-wrap:anywhere;}.directory-heading{display:flex;gap:8px;align-items:center;h2{margin:0;}}.help-content{max-width:360px;line-height:1.8;}.theme-management{min-width:0;color:var(--color-text);}.toolbar,.actions{display:flex;gap:12px;flex-wrap:wrap;align-items:center;}.toolbar{justify-content:space-between;margin:20px 0;}.management-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:24px;}.panel{padding:24px;border:1px solid var(--gray-150);border-radius:8px;min-width:0;}h2{font-size:18px;}h3{font-size:16px;}label{display:flex;flex-direction:column;gap:8px;margin:20px 0;}.help,small{font-size:12px;color:var(--color-text-secondary);line-height:1.8;}.source{display:block;width:100%;padding:16px;margin:8px 0;text-align:left;background:var(--gray-0);border:1px solid var(--gray-150);border-radius:6px;color:inherit;cursor:pointer;small{display:block;margin-top:6px;}}.source[aria-current]{border-color:var(--main-color);background:var(--main-10);}.version{display:flex;justify-content:space-between;gap:16px;padding:20px 0;border-bottom:1px solid var(--gray-150);flex-wrap:wrap;p {margin-bottom: 0;}}.digest{overflow-wrap:anywhere;font-size:12px;}.maintenance{margin-top:32px;padding-top:20px;border-top:1px solid var(--gray-150);}.preview-notice{background:var(--color-warning-50);color:var(--color-warning-900);padding:12px;}.theme-host{min-height:600px;}button:focus-visible{outline:2px solid var(--main-color);outline-offset:3px;}@media(max-width:768px){.management-grid{grid-template-columns:1fr;}.panel{padding:16px;}}
</style>
