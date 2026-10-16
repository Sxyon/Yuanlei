<script setup>
import { computed, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
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
const sourceProjectId = ref(props.projectId), selectionVersionId = ref(''), selectionRef = ref(null)
const mode = ref(route.query.theme_action === 'select' ? 'selection' : 'catalog'), scope = ref('personal')
const sources = ref([]), activeId = ref(''), candidate = shallowRef(null), definition = ref(''), error = ref(''), notice = ref(''), busy = ref(false)
const createOpen = ref(false), createName = ref(''), createKind = ref('personal'), operation = ref(''), reason = ref(''), audit = shallowRef(null), preview = shallowRef(null)
let generation = 0
const active = computed(() => sources.value.find(item => item.id === activeId.value))
const visible = computed(() => sources.value.filter(item => item.kind === scope.value))
const project = computed(() => props.projects.find(item => item.id === props.projectId))
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
onMounted(() => { window.addEventListener('beforeunload',beforeUnload) })
async function load(confirmDiscard = false) {
  if(confirmDiscard && !await canDiscard()) return
  const token = ++generation, id = sourceProjectId.value
  busy.value = true; error.value = ''; sources.value = []; activeId.value = ''; candidate.value = null; preview.value = null; audit.value = null; operation.value = ''
  try { const result = await projectThemeApi.catalog(id); if (token === generation) sources.value = result.sources }
  catch (cause) { if (token === generation) error.value = cause.message }
  finally { if (token === generation) busy.value = false }
}
async function run(action) {
  const token = generation
  busy.value = true; error.value = ''; notice.value = ''
  try { await action(token) } catch (cause) { if (token === generation) error.value = cause.message || '操作失败；原选择保留' }
  finally { if (token === generation) busy.value = false }
}
async function openSource(source) {
  if(!await canDiscard()) return
  const token = ++generation; activeId.value = source.id; candidate.value = null; audit.value = null; preview.value = null; operation.value = ''; notice.value = ''; error.value = ''
  mode.value = source.kind === 'builtin' ? 'versions' : 'candidate'
  if (source.kind === 'builtin') { busy.value = false; return }
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
  const loader = { readAsset: ({alias,signal}) => projectThemeApi.asset({...assetScope,alias,signal}) }
  preview.value = { package: pack, adapter: createSyntheticAdapter(loader), returnMode: mode.value }
  mode.value = 'preview'
}
watch(() => [sourceProjectId.value, user.uid], () => load(), { immediate: true })
watch(() => props.projectId, id => { if(props.stayInProject) sourceProjectId.value=id })
async function assignVersion(id = '') {
  if (!await canDiscard()) return
  selectionVersionId.value = id
  mode.value = 'selection'
}
async function changeSourceProject(id) {
  if (await canDiscard()) sourceProjectId.value = id || ''
}
async function changeTarget(id) {
  emit('project',id)
}
defineExpose({ canDiscard, openPreview: value => run(() => showPreview(value)), showCatalog: async () => { if(await canDiscard()) mode.value = 'catalog' } })
onUnmounted(() => { generation++; window.removeEventListener('beforeunload',beforeUnload) })
</script>
<template>
  <section class="theme-management">
    <div class="toolbar"><p>主题维护 · 候选、版本与项目选择分别提交</p><div class="actions"><RouterLink :to="{name:'ProjectThemePreviewView'}">S03 合成样例</RouterLink><RouterLink v-if="project" :to="{name:'ProjectDashboardComp',params:{project_id:project.id}}">返回项目：{{project.name}}</RouterLink><a-button v-else @click="router.push({name:'ProjectsComp'})">返回项目列表</a-button><a-button :loading="busy" @click="load(true)">刷新目录</a-button></div></div>
    <a-alert v-if="error" type="error" show-icon :message="error" /><a-alert v-if="notice" type="success" show-icon :message="notice" />
    <template v-if="mode==='preview' && preview"><div class="toolbar"><a-button @click="mode=preview.returnMode;preview=null">返回维护 / 选择</a-button><p class="preview-notice">包定义及包内资源真实读取；业务及项目文件内容为合成预览，不保存项目选择。</p></div><ThemeHost :theme-package="preview.package" project-id="preview-market" project-label="隔离合成项目" :user-id="String(user.uid)" :adapter="preview.adapter" simulation /></template>
    <template v-else>
      <div v-if="!stayInProject" class="toolbar"><h2>项目分配</h2><a-button @click="assignVersion()">选择项目并分配主题</a-button></div>
      <ProjectThemeSelection v-if="mode==='selection'" ref="selectionRef" :project-id="projectId" :projects="projects" :initial-version-id="selectionVersionId" :stay-in-project="stayInProject" @selected="value=>emit('selected',value)" @project="changeTarget" @cancel="mode='catalog'" />
      <div class="toolbar"><div class="actions"><a-radio-group :value="scope" @change="async event=>{if(await canDiscard()){scope=event.target.value;mode='catalog';activeId=''}}" :options="[{value:'builtin',label:'平台内置'},{value:'personal',label:'个人公共'},{value:'project',label:'项目专属'}]" /><a-select :value="sourceProjectId || undefined" :options="projects.map(p=>({value:p.id,label:p.name}))" placeholder="来源所属项目（非分配目标）" aria-label="主题来源所属项目" :disabled="stayInProject || scope!=='project'" allow-clear @change="changeSourceProject" /></div><a-button type="primary" :disabled="busy" @click="createOpen=true">建立来源</a-button></div>
      <div class="management-grid"><section class="panel"><h2>来源目录</h2><p class="help">个人公共供你自己的多个项目复用；专属仅限所属项目。</p><p v-if="busy && !sources.length" role="status">正在读取有权目录…</p><a-empty v-else-if="!visible.length" :description="scope==='project' && !sourceProjectId ? '先选择有权项目' : '暂无来源，可复制内置版本或建立来源'" /><button v-for="source in visible" :key="source.id" class="source" :aria-current="source.id===activeId ? 'true':undefined" @click="openSource(source)"><strong>{{source.name}}</strong><small>{{statusText(source.status)}} · {{source.versions.length}} 个版本</small></button></section>
      <section class="panel"><template v-if="active"><div class="toolbar"><div><h2>{{active.name}}</h2><p class="help">{{active.description}} · {{statusText(active.status)}}</p></div><div class="actions"><a-button v-if="mutable" @click="openSource(active)">候选</a-button><a-button @click="mode='versions'">发布版本</a-button><a-button v-if="mutable" @click="run(()=>inspect())">维护对账</a-button></div></div>
        <template v-if="mode==='candidate' && mutable"><p>候选修订 {{candidate?.source.candidate_revision || 0}}；已发布版本保持原字节。</p><label class="upload">替换候选 ZIP<input type="file" accept=".zip,application/zip" aria-label="上传候选ZIP" :disabled="busy" @change="upload" /></label><label v-if="candidate?.package">manifest / theme 受控定义<a-textarea v-model:value="definition" :rows="18" :disabled="busy" aria-label="候选JSON定义" /></label><p v-else class="help">先上传候选ZIP，或从内置版本复制完整包。</p><div class="actions"><a-button :disabled="!candidate?.package || busy" @click="run(save)">保存并校验候选</a-button><a-button :disabled="!candidate?.package || dirty || busy" @click="run(()=>showPreview())">隔离预览</a-button><a-popconfirm title="发布已保存候选的新版本？不改变项目选择。" @confirm="run(publish)"><a-button type="primary" :disabled="!candidate?.package || dirty || active.status!=='active' || busy">发布已保存候选</a-button></a-popconfirm></div><p v-if="dirty" role="status">候选存在未保存修改，请先保存并校验。</p><p class="help">编辑文本需先保存；预览及发布消费服务端已保存修订。校验失败明确定位字段；新资源用完整ZIP替换。</p></template>
        <template v-if="(mode==='versions' || mode==='selection')"><p v-if="!active.versions.length">尚无发布版本，先维护并发布候选。</p><article v-for="version in active.versions" :key="version.id" class="version"><div><strong>{{active.name}} · {{version.version}}</strong><p class="help">{{version.created_at}} · {{version.size}} bytes · 发布者 {{version.created_by || '平台'}}</p><details><summary>追溯信息</summary><p>版本 {{version.id}} · 候选修订 {{version.candidate_revision}}</p><p class="digest">SHA-256 {{version.digest}}</p></details></div><div class="actions"><a-button :disabled="busy || active.status==='withdrawn'" @click="run(()=>showPreview({versionId:version.id}))">预览版本</a-button><a-button :disabled="busy || active.status==='withdrawn'" @click="run(()=>create(version.id))">复制为个人来源</a-button><a-button :disabled="active.status!=='active'" @click="assignVersion(version.id)">分配到项目</a-button></div></article></template>
        <template v-if="mode==='audit'"><h3>数据库引用与文件对账</h3><p class="help">只读检查不删除文件。清理在来源锁内重查引用，避开发布和候选保存；被引用包保留。</p><div class="actions"><a-button :disabled="busy" @click="run(()=>inspect())">重新检查</a-button><a-popconfirm title="重新查询引用后，清理此来源未使用完整包与临时残留？" @confirm="run(()=>inspect(true))"><a-button :disabled="busy">清理未引用文件</a-button></a-popconfirm></div><ul><li v-for="(item,index) in audit?.files" :key="index">{{fileStateText(item.state)}} <span class="digest">{{item.digest}}</span></li></ul><details><summary>维护历史与部署恢复说明</summary><p v-for="(item,index) in audit?.history" :key="index">{{item.created_at}} · {{item.action}} · {{item.reason}} · {{item.actor_uid}}</p><p>部署维护者暂停写入后同时备份PG和主题文件，恢复到隔离环境逐版本与绑定对账；普通用户不持有数据库恢复权限。</p></details></template>
        <div v-if="mutable" class="maintenance"><h3>来源操作</h3><div class="actions"><a-button v-if="active.status==='active'" @click="operation='disabled';reason=''">停用来源</a-button><a-button v-if="active.status!=='withdrawn'" danger @click="operation='withdrawn';reason=''">安全撤回</a-button><a-button v-if="active.status!=='active'" @click="operation='active';reason=''">恢复来源</a-button></div><p class="help">停用停止新发布和新选择，既有版本继续加载；安全撤回阻止全部版本加载，原绑定及历史保留。</p><a-alert v-if="active.reason" type="warning" :message="active.reason" /></div>
      </template><a-empty v-else description="选择一个来源查看候选与发布历史" /></section></div>
    </template>
    <a-modal v-model:open="createOpen" title="建立主题来源" :confirm-loading="busy" @ok="run(()=>create())"><label>名称<a-input v-model:value="createName" :maxlength="160" /></label><label>归属<a-select v-model:value="createKind" :options="[{value:'personal',label:'个人公共'},{value:'project',label:'当前项目专属',disabled:!sourceProjectId}]" /></label><p>身份由服务生成；建立后上传完整ZIP候选，不自动发布或选择。</p></a-modal>
    <a-modal :open="Boolean(operation)" title="确认来源操作" :confirm-loading="busy" @cancel="operation=''" @ok="run(maintain)"><p>来源：{{active?.name}}</p><p>{{operation==='disabled'?'停止新发布、新选择；既有绑定继续加载。':operation==='withdrawn'?'来源全部版本停止加载；所有已绑定项目保留原选择并显示原因。':'恢复来源使用；原项目版本与映射保留。'}}</p><label>原因（撤回及恢复撤回必填）<a-textarea v-model:value="reason" :maxlength="2000" /></label></a-modal>
  </section>
</template>
<style scoped lang="less">
.theme-management{min-width:0;color:var(--color-text);}.toolbar,.actions{display:flex;gap:12px;flex-wrap:wrap;align-items:center;}.toolbar{justify-content:space-between;margin:20px 0;}.management-grid{display:grid;grid-template-columns:260px minmax(0,1fr);gap:24px;}.panel{padding:24px;border:1px solid var(--gray-150);border-radius:8px;min-width:0;}h2{font-size:18px;}h3{font-size:16px;}label{display:flex;flex-direction:column;gap:8px;margin:20px 0;}.help,small{font-size:12px;color:var(--color-text-secondary);line-height:1.8;}.source{display:block;width:100%;padding:16px;margin:8px 0;text-align:left;background:var(--gray-0);border:1px solid var(--gray-150);border-radius:6px;color:inherit;cursor:pointer;small{display:block;margin-top:6px;}}.source[aria-current]{border-color:var(--main-color);background:var(--main-10);}.version{display:flex;justify-content:space-between;gap:16px;padding:20px 0;border-bottom:1px solid var(--gray-150);flex-wrap:wrap;}.digest{overflow-wrap:anywhere;font-size:12px;}.maintenance{margin-top:32px;padding-top:20px;border-top:1px solid var(--gray-150);}.preview-notice{background:var(--color-warning-50);color:var(--color-warning-900);padding:12px;}.theme-host{min-height:600px;}button:focus-visible{outline:2px solid var(--main-color);outline-offset:3px;}@media(max-width:768px){.management-grid{grid-template-columns:1fr;}.panel{padding:16px;}}
</style>
