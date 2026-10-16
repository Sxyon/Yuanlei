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
const createOpen = ref(false), createName = ref(''), createKind = ref('personal'), operation = ref(''), reason = ref(''), audit = shallowRef(null), preview = shallowRef(null)
let generation = 0, catalogSequence = 0
const active = computed(() => sources.value.find(item => item.id === activeId.value))
const showHistory = ref(false)
const visible = computed(() => sources.value.filter(item => item.kind === scope.value && (showHistory.value || item.status === 'active')))
const historical = computed(() => sources.value.filter(item => item.kind === scope.value && item.status !== 'active').length)
const mutable = computed(() => active.value && active.value.kind !== 'builtin')
const dirty = computed(() => {
  if (!candidate.value?.package) return false
  try { return JSON.stringify(JSON.parse(definition.value)) !== JSON.stringify({ manifest: candidate.value.package.manifest, theme: candidate.value.package.theme }) }
  catch { return true }
})
useProjectThemeEdit('项目主题候选定义', () => props.stayInProject ? props.projectId : '', () => dirty.value, () => {definition.value=JSON.stringify({manifest:candidate.value.package.manifest,theme:candidate.value.package.theme},null,2)}, () => busy.value)
const fileStateText = value => ({referenced:'已引用且字节有效',orphan:'完整未引用包',temporary:'临时残留',removed_orphan:'已清理未引用包',removed_temporary:'已清理临时残留',missing:'引用包缺失',package_missing:'引用包缺失',package_corrupt:'包字节损坏',unsafe_entry:'非普通文件，拒绝清理'}[value] || `校验失败：${value}`)
const statusText = value => ({ active: '可新选择', disabled: '已停用，既有选择可加载', withdrawn: '安全撤回，加载已拒绝' }[value])
async function canDiscard(includeSelection = true) {
  if (includeSelection && selectionRef.value && !await selectionRef.value.canDiscard()) return false
  if(!dirty.value) return true
  return new Promise(resolve => Modal.confirm({title:'放弃未保存的主题候选？',okText:'放弃并离开',cancelText:'继续编辑',onOk:()=>resolve(true),onCancel:()=>resolve(false)}))
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
  try { await action(token); if (token === generation) await refreshCatalog() } catch (cause) { if (token === generation) error.value = cause.message || '操作失败；原选择保留' }
  finally { if (token === generation) busy.value = false }
}
async function openSource(source) {
  if(!await canDiscard()) return
  const token = ++generation; activeId.value = source.id; candidate.value = null; audit.value = null; preview.value = null; operation.value = ''; notice.value = ''; error.value = ''
  mode.value = source.kind === 'builtin' ? 'versions' : 'candidate'
  if (source.kind === 'builtin') { await run(async () => {}); return }
  await run(async () => {
    const result = await projectThemeApi.candidate(source.id, sourceProjectId.value)
    if (token !== generation || activeId.value !== source.id) return
    candidate.value = result; definition.value = result.package ? JSON.stringify({ manifest: result.package.manifest, theme: result.package.theme }, null, 2) : ''
  })
}
async function upload(event) {
  const file = event.target.files?.[0]; event.target.value = ''
  if (!file || !active.value || !await canDiscard()) return
  const source = active.value, revision = candidate.value?.source.candidate_revision || source.candidate_revision
  await run(async token => {
    const result = await projectThemeApi.upload(source.id, sourceProjectId.value, revision, file)
    if (token !== generation || activeId.value !== source.id) return
    candidate.value = result; Object.assign(source, result.source); definition.value = JSON.stringify({manifest:result.package.manifest,theme:result.package.theme},null,2)
    notice.value = '候选ZIP已保存并完成校验；尚未发布，不改变项目选择。'
  })
}
async function save(token) {
  const body = JSON.parse(definition.value), source = active.value
  const result = await projectThemeApi.edit(source.id, sourceProjectId.value, { ...body, expected_revision: candidate.value.source.candidate_revision })
  if (token !== generation || activeId.value !== source.id) return
  candidate.value = result; Object.assign(source, result.source); definition.value = JSON.stringify({ manifest: result.package.manifest, theme: result.package.theme }, null, 2); notice.value = '候选已保存并校验，旧发布版本与项目选择保留。'
}
async function publish(token) {
  if (dirty.value) throw new Error('候选存在未保存修改，请先保存并校验')
  const source = active.value
  const version = await projectThemeApi.publish(source.id, sourceProjectId.value, candidate.value.source.candidate_revision)
  if (token !== generation || activeId.value !== source.id) return
  source.versions = [version, ...source.versions.filter(item=>item.id!==version.id)]
  emit('catalog-changed')
  notice.value = `已发布 ${source.name} · ${version.version}；项目选择未改变。`; mode.value = 'versions'
}
async function create(copyVersion = null) {
  if(!await canDiscard()) return
  const token = generation
  const result = await projectThemeApi.create({ name: copyVersion ? `${active.value.name}（个人副本）` : createName.value, kind: copyVersion ? 'personal' : createKind.value, project_id: !copyVersion && createKind.value==='project' ? sourceProjectId.value : null, copy_version_id: copyVersion, copy_project_id: copyVersion ? sourceProjectId.value || null : null })
  if (token !== generation) return
  sources.value.push({...result,versions:[]}); createOpen.value = false; scope.value = result.kind
  candidate.value = null
  await openSource(result)
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
  audit.value = result; mode.value = 'audit'
}
async function showPreview({versionId,projectId=sourceProjectId.value}={}) {
  if (!versionId && dirty.value) throw new Error('候选存在未保存修改，请先保存并校验')
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
    <a-alert v-if="error" type="error" show-icon :message="error" /><a-alert v-if="notice" type="success" show-icon :message="notice" />
    <template v-if="mode==='preview' && preview"><div class="toolbar"><a-button @click="mode=preview.returnMode;preview=null">返回维护 / 选择</a-button><p class="preview-notice">包定义及包内资源真实读取；业务及项目文件内容为合成预览，不保存项目选择。</p></div><ThemeHost :theme-package="preview.package" project-id="preview-market" project-label="隔离合成项目" :user-id="String(user.uid)" :adapter="preview.adapter" simulation /></template>
    <template v-else>
      <div class="toolbar"><div class="actions"><a-radio-group :disabled="busy" :value="scope" @change="async event=>{if(await canDiscard()){scope=event.target.value;mode='catalog';activeId='';candidate=null;definition='';await run(refreshCatalog)}}" :options="[{value:'builtin',label:'平台内置'},{value:'personal',label:'个人公共'},{value:'project',label:'项目专属'}]" /><a-select :value="sourceProjectId || undefined" :options="projects.map(p=>({value:p.id,label:p.name}))" placeholder="来源所属项目（非分配目标）" aria-label="主题来源所属项目" :disabled="busy || stayInProject || scope!=='project'" allow-clear @change="changeSourceProject" /></div><div class="actions"><a-button v-if="!stayInProject" :disabled="busy" @click="assignVersion()">项目主题设置</a-button><a-button type="primary" :disabled="busy" @click="createOpen=true">建立来源</a-button>    <a-popover trigger="click" title="主题使用与维护"><template #content><div class="help-content"><p>选择项目后可分配主题，也可从准确发布版本发起分配。成功后在本页核实结果。</p><p>候选用于编辑；发布生成不可变版本；分配才改变项目选择。预览不保存选择，新发布不会自动替换项目版本。</p><p>个人公共供自己的多个项目复用；项目专属仅限所属项目。停用版本保留历史及已有绑定，可在历史目录追溯。</p><p>目录随来源切换、创建、保存、发布、维护及分配操作自动核对；重新聚焦时也会核对。</p></div></template><a-button type="text" aria-label="主题管理帮助" title="主题管理帮助"><CircleHelp :size="18" /></a-button></a-popover>
</div></div>
      <div class="management-grid"><section class="panel"><header class="directory-heading"><h2>来源目录</h2><a-button v-if="historical" type="text" aria-label="查看历史来源" :aria-pressed="showHistory" :title="showHistory ? '隐藏历史来源' : '查看历史来源'" @click="showHistory=!showHistory"><History :size="17" /></a-button></header><p v-if="showHistory" class="help">含 {{historical}} 个历史来源，停用版本保留追溯。</p><p v-if="busy && !sources.length" role="status">正在读取有权目录…</p><a-empty v-else-if="!visible.length" :description="scope==='project' && !sourceProjectId ? '先选择有权项目' : '暂无来源，可复制内置版本或建立来源'" /><button v-for="source in visible" :key="source.id" class="source" :disabled="busy" :aria-current="source.id===activeId ? 'true':undefined" @click="openSource(source)"><strong>{{source.name}}</strong><small>{{statusText(source.status)}} · {{source.versions.length}} 个版本</small></button></section>
      <section class="panel"><template v-if="active"><div class="toolbar"><div><h2>{{active.name}}</h2><p class="help">{{active.description}} · {{statusText(active.status)}}</p></div><div class="actions"><a-button v-if="mutable" @click="openSource(active)">候选</a-button><a-button @click="mode='versions'">发布版本</a-button><a-button v-if="mutable" @click="run(()=>inspect())">维护对账</a-button></div></div>
        <template v-if="mode==='candidate' && mutable"><p>候选修订 {{candidate?.source.candidate_revision || 0}}；已发布版本保持原字节。</p><label class="upload">替换候选 ZIP<input type="file" accept=".zip,application/zip" aria-label="上传候选ZIP" :disabled="busy" @change="upload" /></label><label v-if="candidate?.package">manifest / theme 受控定义<a-textarea v-model:value="definition" :rows="18" :disabled="busy" aria-label="候选JSON定义" /></label><p v-else class="help">先上传候选ZIP，或从内置版本复制完整包。</p><div class="actions"><a-button :disabled="!candidate?.package || busy" @click="run(save)">保存并校验候选</a-button><a-button :disabled="!candidate?.package || dirty || busy" @click="run(()=>showPreview())">隔离预览</a-button><a-popconfirm title="发布已保存候选的新版本？不改变项目选择。" @confirm="run(publish)"><a-button type="primary" :disabled="!candidate?.package || dirty || active.status!=='active' || busy">发布已保存候选</a-button></a-popconfirm></div><p v-if="dirty" role="status">候选存在未保存修改，请先保存并校验。</p><p class="help">编辑文本需先保存；预览及发布消费服务端已保存修订。校验失败明确定位字段；新资源用完整ZIP替换。</p></template>
        <template v-if="mode==='versions'"><p v-if="!active.versions.length">尚无发布版本，先维护并发布候选。</p><article v-for="version in active.versions" :key="version.id" class="version"><div><strong>{{active.name}} · {{version.version}}</strong><p class="help">{{version.created_at}} · {{version.size}} bytes · 发布者 {{version.created_by || '平台'}}</p><p class="help digest">版本 {{version.id}} · 候选修订 {{version.candidate_revision}}</p><p class="help digest">SHA-256 {{version.digest}}</p></div><div class="actions"><a-button :disabled="busy || active.status==='withdrawn'" @click="run(()=>showPreview({versionId:version.id}))">预览版本</a-button><a-button :disabled="busy || active.status==='withdrawn'" @click="run(()=>create(version.id))">复制为个人来源</a-button><a-button :disabled="active.status!=='active'" @click="assignVersion(version.id)">分配到项目</a-button></div></article></template>
        <template v-if="mode==='audit'"><h3>数据库引用与文件对账</h3><p class="help">只读检查不删除文件。清理在来源锁内重查引用，避开发布和候选保存；被引用包保留。</p><div class="actions"><a-button :disabled="busy" @click="run(()=>inspect())">重新检查</a-button><a-popconfirm title="重新查询引用后，清理此来源未使用完整包与临时残留？" @confirm="run(()=>inspect(true))"><a-button :disabled="busy">清理未引用文件</a-button></a-popconfirm></div><ul><li v-for="(item,index) in audit?.files" :key="index">{{fileStateText(item.state)}} <span class="digest">{{item.digest}}</span></li></ul><details><summary>维护历史与部署恢复说明</summary><p v-for="(item,index) in audit?.history" :key="index">{{item.created_at}} · {{item.action}} · {{item.reason}} · {{item.actor_uid}}</p><p>部署维护者暂停写入后同时备份PG和主题文件，恢复到隔离环境逐版本与绑定对账；普通用户不持有数据库恢复权限。</p></details></template>
        <div v-if="mutable" class="maintenance"><h3>来源操作</h3><div class="actions"><a-button v-if="active.status==='active'" @click="operation='disabled';reason=''">停用来源</a-button><a-button v-if="active.status!=='withdrawn'" danger @click="operation='withdrawn';reason=''">安全撤回</a-button><a-button v-if="active.status!=='active'" @click="operation='active';reason=''">恢复来源</a-button></div><p class="help">停用停止新发布和新选择，既有版本继续加载；安全撤回阻止全部版本加载，原绑定及历史保留。</p><a-alert v-if="active.reason" type="warning" :message="active.reason" /></div>
      </template><a-empty v-else description="选择一个来源查看候选与发布历史" /></section></div>
    </template>
    <a-modal :open="selectionOpen" title="项目主题设置" :footer="null" :width="1100" :mask-closable="false" :destroy-on-close="true" @cancel="closeSelection">
      <ProjectThemeSelection v-if="selectionOpen" ref="selectionRef" :project-id="projectId" :projects="projects" :initial-version-id="selectionVersionId" :stay-in-project="stayInProject" embedded @selected="selected" @project="changeTarget" @cancel="closeSelection" />
    </a-modal>
    <a-modal v-model:open="previewProjectOpen" title="选择预览项目" ok-text="开始只读预览" :ok-button-props="{disabled:!previewProjectId}" @ok="enterWorkspacePreview">
      <p>使用该项目有权读取的真实数据，在同一项目页面中查看准确版本效果。预览只读，不修改项目选择或业务。</p>
      <a-select v-model:value="previewProjectId" :options="projects.map(item=>({value:item.id,label:item.name}))" aria-label="主题预览项目" placeholder="选择有权项目" style="width:100%" />
      <p v-if="!projects.length">暂无有权项目，请先建立项目。</p>
    </a-modal>
    <a-modal v-model:open="createOpen" title="建立主题来源" :confirm-loading="busy" @ok="run(()=>create())"><label>名称<a-input v-model:value="createName" :maxlength="160" /></label><label>归属<a-select v-model:value="createKind" :options="[{value:'personal',label:'个人公共'},{value:'project',label:'当前项目专属',disabled:!sourceProjectId}]" /></label><p>身份由服务生成；建立后上传完整ZIP候选，不自动发布或选择。</p></a-modal>
    <a-modal :open="Boolean(operation)" title="确认来源操作" :confirm-loading="busy" @cancel="operation=''" @ok="run(maintain)"><p>来源：{{active?.name}}</p><p>{{operation==='disabled'?'停止新发布、新选择；既有绑定继续加载。':operation==='withdrawn'?'来源全部版本停止加载；所有已绑定项目保留原选择并显示原因。':'恢复来源使用；原项目版本与映射保留。'}}</p><label>原因（撤回及恢复撤回必填）<a-textarea v-model:value="reason" :maxlength="2000" /></label></a-modal>
  </section>
</template>
<style scoped lang="less">
.directory-heading{display:flex;gap:8px;align-items:center;h2{margin:0;}}.help-content{max-width:360px;line-height:1.8;}.theme-management{min-width:0;color:var(--color-text);}.toolbar,.actions{display:flex;gap:12px;flex-wrap:wrap;align-items:center;}.toolbar{justify-content:space-between;margin:20px 0;}.management-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:24px;}.panel{padding:24px;border:1px solid var(--gray-150);border-radius:8px;min-width:0;}h2{font-size:18px;}h3{font-size:16px;}label{display:flex;flex-direction:column;gap:8px;margin:20px 0;}.help,small{font-size:12px;color:var(--color-text-secondary);line-height:1.8;}.source{display:block;width:100%;padding:16px;margin:8px 0;text-align:left;background:var(--gray-0);border:1px solid var(--gray-150);border-radius:6px;color:inherit;cursor:pointer;small{display:block;margin-top:6px;}}.source[aria-current]{border-color:var(--main-color);background:var(--main-10);}.version{display:flex;justify-content:space-between;gap:16px;padding:20px 0;border-bottom:1px solid var(--gray-150);flex-wrap:wrap;}.digest{overflow-wrap:anywhere;font-size:12px;}.maintenance{margin-top:32px;padding-top:20px;border-top:1px solid var(--gray-150);}.preview-notice{background:var(--color-warning-50);color:var(--color-warning-900);padding:12px;}.theme-host{min-height:600px;}button:focus-visible{outline:2px solid var(--main-color);outline-offset:3px;}@media(max-width:768px){.management-grid{grid-template-columns:1fr;}.panel{padding:16px;}}
</style>
