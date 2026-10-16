import assert from 'node:assert/strict'
import { setImmediate } from 'node:timers'
import { after, before, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { Modal } from 'ant-design-vue'
import { createServer } from 'vite'
let vite, View, api
before(async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  globalThis.document = {addEventListener(){},removeEventListener(){}}
  globalThis.window = { addEventListener() {}, removeEventListener() {} }
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ default: View } = await vite.ssrLoadModule('/src/components/project/ProjectThemeManager.vue'))
  ;({ projectThemeApi: api } = await vite.ssrLoadModule('/src/apis/project_theme_api.js'))
})
after(async () => {
  await vite?.close()
  delete globalThis.localStorage
  delete globalThis.window
  delete globalThis.document
})
const renderer = createRenderer({
  createElement: () => ({}),
  createText: () => ({}),
  createComment: () => ({}),
  insert() {},
  remove() {},
  setText() {},
  setElementText() {},
  patchProp() {},
  parentNode: () => null,
  nextSibling: () => null
})
test('主题候选取消来源切换和真实路由离开时保留未保存正文', async (t) => {
  setActivePinia(createPinia())
  const sources = [
    { id: 'a', kind: 'project', versions: [] },
    { id: 'b', kind: 'project', versions: [] }
  ]
  t.mock.method(api, 'catalog', async () => ({ sources }))
  t.mock.method(api, 'candidate', async (id) => ({
    source: { id, candidate_revision: 1 },
    package: { manifest: {}, theme: { name: id } }
  }))
  let confirmation, instance
  t.mock.method(Modal, 'confirm', (options) => {
    confirmation = options
    return { destroy() {} }
  })
  const Component = {
    ...View,
    render() {
      instance = getCurrentInstance()
      return h('div')
    }
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      {
        path: '/settings',
        component: Component,
        props: { projectId: 'test-project', projects: [], stayInProject: true }
      },
      { path: '/topics', component: { render: () => h('div') } }
    ]
  })
  await router.push('/settings')
  await router.isReady()
  const app = renderer.createApp({ render: () => h(RouterView) })
  app.use(router)
  app.provide(ssrContextKey, { modules: new Set() })
  app.mount({})
  t.after(() => app.unmount())
  await nextTick()
  const state = () => instance.setupState
  await state().openSource(sources[0])
  state().definition = JSON.stringify({ manifest: {}, theme: { name: '未保存候选' } })
  const switching = state().openSource(sources[1])
  assert.equal(confirmation.title, '放弃未保存的主题编辑草稿？')
  confirmation.onCancel()
  await switching
  assert.equal(state().activeId, 'a')
  assert.match(state().definition, /未保存候选/)
  confirmation = null
  const leaving = router.push('/topics')
  for (let i = 0; i < 20 && !confirmation; i++)
    await new Promise((resolve) => setImmediate(resolve))
  assert.ok(confirmation)
  confirmation.onCancel()
  await leaving
  assert.equal(router.currentRoute.value.path, '/settings')
  assert.match(state().definition, /未保存候选/)
})


async function mountManager(t, sources) {
  setActivePinia(createPinia())
  t.mock.method(api,'catalog',async()=>({sources}))
  t.mock.method(api,'candidate',async id=>({source:sources.find(s=>s.id===id),package:{manifest:{},theme:{name:'草稿',version:'1'}}}))
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/',component:{render:()=>null}}]})
  await router.push('/')
  let instance
  const Host={...View,render(){instance=getCurrentInstance();return h('div')}}
  const app=renderer.createApp({render:()=>h(Host,{projects:[],projectId:''})});app.use(router);app.provide(ssrContextKey,{modules:new Set()});app.mount({});t.after(()=>app.unmount())
  await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick()
  return instance.setupState
}
const original=()=>({id:'builtin',name:'原内置',kind:'builtin',status:'active',versions:[{id:'exact-v',version:'3.0.0'}]})
const copied=()=>({id:'new-copy',name:'我的副本',kind:'personal',status:'active',candidate_digest:'a',candidate_revision:1,copied_from_version_id:'exact-v',versions:[]})
test('查看模式有稳定草稿，同模式不重读；未保存不能发布',async t=>{
  const state=await mountManager(t,[copied()]);await state.openSource(copied())
  state.definition='未保存JSON'
  t.mock.method(api,'candidate',async()=>{throw new Error('不能重载本地草稿')})
  state.showMode('versions');state.showMode('candidate');state.showMode('candidate')
  assert.equal(state.definition,'未保存JSON');assert.equal(state.mode,'candidate')
  t.mock.method(api,'publish',async()=>{throw new Error('不得提交未保存')})
  await assert.rejects(state.publish(),/未保存/)
})
test('复制先确认准确出处与名称，成功进入草稿且不发布应用',async t=>{
  const state=await mountManager(t,[original()]);await state.openSource(original())
  let createdBody
  t.mock.method(api,'create',async body=>{createdBody=body;return copied()})
  t.mock.method(api,'publish',async()=>{assert.fail('复制不发布')})
  t.mock.method(api,'select',async()=>{assert.fail('复制不应用')})
  state.prepareCreate(original().versions[0]);assert.equal(createdBody,undefined)
  assert.equal(state.copyFrom.id,'exact-v');state.createName='我的副本'
  await state.create()
  assert.equal(createdBody.copy_version_id,'exact-v');assert.equal(createdBody.name,'我的副本');assert.equal(createdBody.kind,'personal')
  assert.equal(state.activeId,'new-copy');assert.equal(state.mode,'candidate');assert.equal(state.scope,'personal');assert.match(state.notice,/尚未发布、尚未应用/);assert.equal(state.pendingCreate,null)
})
test('复制身份已提交但候选失败，核实原身份后提供上传恢复，不重发创建',async t=>{
  const state=await mountManager(t,[original()]);await state.openSource(original())
  state.prepareCreate(original().versions[0]);state.createName='我的副本'
  let posted=false
  t.mock.method(api,'create',async()=>{posted=true;throw new Error('copy_incomplete')})
  t.mock.method(api,'catalog',async()=>({sources:posted?[original(),{...copied(),candidate_digest:null,candidate_revision:0}]:[original()]}))
  t.mock.method(api,'candidate',async()=>({source:{...copied(),candidate_digest:null,candidate_revision:0},package:null}))
  await state.create()
  assert.equal(state.activeId,'new-copy');assert.equal(state.candidate.package,null);assert.equal(state.pendingCreate,null)
  assert.match(state.notice,/身份.*已建立/);assert.match(state.notice,/上传完整 ZIP，不要重新创建/)
})
test('创建响应丢失且目录不可用时保留意图阻止重复POST，重查恢复准确副本',async t=>{
  const state=await mountManager(t,[original()]);await state.openSource(original())
  state.prepareCreate(original().versions[0]);state.createName='我的副本'
  let posted=0,readable=false
  t.mock.method(api,'create',async()=>{posted++;throw new Error('connection lost')})
  t.mock.method(api,'catalog',async()=>{if(posted&&!readable)throw new Error('目录不可用');return {sources:posted?[original(),copied()]:[original()]}})
  await state.create();assert.ok(state.pendingCreate);assert.match(state.error,/无法核实/)
  await assert.rejects(state.create(),/尚未核实/);assert.equal(posted,1)
  readable=true;await state.verifyCreate();assert.equal(state.activeId,'new-copy');assert.equal(state.pendingCreate,null);assert.equal(posted,1)
})
test('多个同名新身份不猜选、不重复创建；存储检查不修改编辑模式',async t=>{
  const state=await mountManager(t,[original()]);await state.openSource(original())
  state.prepareCreate(original().versions[0]);state.createName='我的副本'
  let posted=false
  t.mock.method(api,'create',async()=>{posted=true;throw new Error('lost')})
  t.mock.method(api,'catalog',async()=>({sources:posted?[original(),copied(),{...copied(),id:'other'}]:[original()]}))
  await state.create();assert.equal(state.createMatches.length,2);assert.equal(state.activeId,'builtin');assert.ok(state.pendingCreate)
  await state.locateCreated(copied(),true)
  t.mock.method(api,'audit',async()=>({files:[{state:'referenced'},{state:'orphan'},{state:'package_missing'}],history:[]}))
  await state.inspect();assert.equal(state.mode,'candidate');assert.match(state.storageSummary,/1 个有效引用包，1 项未引用残留，1 项异常/)
})


test('空白主题明确422拒绝后先核目录，释放创建而不自动重试',async t=>{
  const state=await mountManager(t,[original()]);state.prepareCreate();state.createName='被拒绝的空白主题'
  let posts=0
  t.mock.method(api,'create',async()=>{posts++;throw Object.assign(new Error('名称不合法'),{status:422})})
  await state.create();assert.equal(state.pendingCreate,null);assert.match(state.error,/创建被拒绝.*未发现新增副本/)
  assert.equal(posts,1);state.prepareCreate();assert.equal(state.createOpen,true)
})
test('核实副本时取消离开旧草稿，恢复对象与未保存正文都保留且不误报定位',async t=>{
  const state=await mountManager(t,[copied()]);await state.openSource(copied())
  state.definition='保留旧草稿'
  const target={...copied(),id:'recover-copy'}
  state.pendingCreate={body:{name:target.name,kind:'personal',copy_version_id:'exact-v'},beforeIds:['new-copy']}
  t.mock.method(api,'catalog',async()=>({sources:[copied(),target]}))
  t.mock.method(Modal,'confirm',options=>options.onCancel())
  await state.verifyCreate()
  assert.equal(state.activeId,'new-copy');assert.equal(state.definition,'保留旧草稿');assert.ok(state.pendingCreate)
  assert.equal(state.createMatches[0].id,'recover-copy');assert.doesNotMatch(state.notice,/已定位/)
  t.mock.method(Modal,'confirm',options=>options.onOk())
  await state.verifyCreate();assert.equal(state.activeId,'recover-copy');assert.equal(state.pendingCreate,null)
})
