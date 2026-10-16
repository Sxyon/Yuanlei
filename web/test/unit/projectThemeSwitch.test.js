import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, reactive, ssrContextKey } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'
import { setImmediate } from 'node:timers'
let vite, Selection, api, useUserStore
before(async () => {
  globalThis.window = {addEventListener(){},removeEventListener(){}}
  globalThis.localStorage = {getItem:()=>null,setItem(){},removeItem(){}}
  vite = await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  ;({default:Selection} = await vite.ssrLoadModule('/src/components/project/ProjectThemeSelection.vue'))
  ;({projectThemeApi:api} = await vite.ssrLoadModule('/src/apis/project_theme_api.js'))
  ;({useUserStore} = await vite.ssrLoadModule('/src/stores/user.js'))
  globalThis.document={addEventListener(){},removeEventListener(){}}
})
after(async () => {await vite?.close();delete globalThis.localStorage;delete globalThis.window;delete globalThis.document})
const renderer = createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},patchProp(){},parentNode:()=>null,nextSibling:()=>null})
const settle = async () => {await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick()}
const pack = {manifest:{formatVersion:1,componentAbi:2,theme:'theme.json',source:'测试',assets:{},files:{}},theme:{id:'independent',name:'独立定义',version:'3.1',topicLabel:'议题',baseVersion:1,density:'comfortable',accent:'teal',pages:[{id:'unique',title:'阅读',description:'独立',layout:'reading',capability:'topics',blocks:[]}]},reference:'v',digest:'a'.repeat(64)}
async function mount(t) {
  const pinia=createPinia();setActivePinia(pinia);useUserStore().uid='u'
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/manage',name:'Manage',component:{render:()=>null}}]});await router.push('/manage')
  const props=reactive({projectId:'a',projects:[{id:'a',name:'A'},{id:'b',name:'B'}]})
  t.mock.method(api,'catalog',async()=>({sources:[{id:'source',name:'独立',kind:'builtin',status:'active',versions:[{id:'v',version:'3.1',component_abi:2}]}]}))
  t.mock.method(api,'binding',async()=>({binding:null,generation:0,state:'unbound'}))
  t.mock.method(api,'version',async()=>structuredClone(pack))
  t.mock.method(api,'check',async()=>({selectable:true,error:null}))
  let instance
  const Child={...Selection,render(){instance=getCurrentInstance();return h('div')}}
  const app=renderer.createApp({render:()=>h(Child,props)})
  app.use(pinia);app.use(router);app.provide(ssrContextKey,{modules:new Set()});app.mount({});t.after(()=>app.unmount());await settle()
  const state=instance.setupState;state.versionId='v';await state.chooseVersion()
  return {state,props,router}
}
test('提交响应丢失先核绑定，不重发；平台成功留在管理页',async t=>{
  const {state,router}=await mount(t)
  let writes=0
  t.mock.method(api,'select',async()=>{writes++;throw new Error('response lost')})
  t.mock.method(api,'binding',async()=>({state:'ready',generation:1,binding:{version_id:'v',files:{}},package:structuredClone(pack)}))
  await state.save()
  assert.equal(writes,1);assert.equal(router.currentRoute.value.name,'Manage');assert.match(state.notice,/已保存并核实/);assert.equal(state.pending,null)
})
test('已知提交后回读失败明确已保存，核实前禁止第二次PUT',async t=>{
  const {state}=await mount(t);let writes=0
  t.mock.method(api,'select',async()=>{writes++;return {}})
  t.mock.method(api,'binding',async()=>{throw new Error('read failed')})
  await state.save();assert.match(state.error,/已保存，加载失败/);assert.ok(state.pending)
  await state.save();assert.equal(writes,1)
  t.mock.method(api,'binding',async()=>({state:'ready',generation:1,binding:{version_id:'v',files:{}},package:structuredClone(pack)}))
  await state.reconcile();assert.equal(writes,1);assert.equal(state.pending,null)
})
test('双入口409后读新事实，必须再次确认而不是覆盖',async t=>{
  const {state}=await mount(t);let writes=0
  t.mock.method(api,'select',async()=>{writes++;throw Object.assign(new Error('conflict'),{status:409})})
  t.mock.method(api,'binding',async()=>({state:'ready',generation:2,binding:{version_id:'other',files:{}},package:structuredClone(pack)}))
  await state.save();assert.equal(writes,1);assert.match(state.error,/选择冲突/);assert.equal(state.current.generation,2);assert.equal(state.condition,null)
})
test('切项目后旧版本响应不能覆盖新项目的定义与条件',async t=>{
  const {state,props}=await mount(t)
  let release
  t.mock.method(api,'version',()=>new Promise(resolve=>{release=resolve}))
  const old=state.chooseVersion();props.projectId='b';await settle()
  release(structuredClone(pack));await old
  assert.equal(state.bundle,null);assert.equal(state.current.generation,0);assert.equal(state.versionId,'')
})


test('应用预检期间重复点击不启动第二次检查，切目标后迟到确认不得写新目标',async t=>{
  const {state,props}=await mount(t);let release,writes=0
  t.mock.method(api,'check',()=>new Promise(resolve=>{release=resolve}))
  t.mock.method(api,'select',async()=>{writes++})
  const first=state.save();await state.save();assert.equal(state.saving,true);assert.equal(api.check.mock.callCount(),1)
  props.projectId='b';await settle();release({selectable:true,error:null});await first
  assert.equal(writes,0);assert.equal(state.pending,null)
})


test('平台重新聚焦读取另一入口的新绑定，保留选择草稿并要求重新确认',async t=>{
  const {state}=await mount(t)
  t.mock.method(api,'binding',async()=>({state:'ready',generation:3,binding:{version_id:'other',files:{}},package:structuredClone(pack)}))
  await state.refreshCurrent()
  assert.equal(state.current.generation,3);assert.equal(state.versionId,'v');assert.ok(state.bundle);assert.equal(state.condition,null);assert.match(state.error,/绑定已变化/)
})


test('平台聚焦的旧回读不能盖过新回读',async t=>{
  const {state}=await mount(t);const waiting=[]
  t.mock.method(api,'binding',()=>new Promise(resolve=>waiting.push(resolve)))
  const old=state.refreshCurrent(),fresh=state.refreshCurrent()
  waiting[1]({state:'unbound',generation:5,binding:null});await fresh
  waiting[0]({state:'unbound',generation:4,binding:null});await old
  assert.equal(state.current.generation,5)
})


test('保存先使已发出的聚焦回读失效，迟到旧generation不能覆盖已核实成功',async t=>{
  const {state}=await mount(t);let release,calls=0
  t.mock.method(api,'binding',async()=>{
    if(++calls===1)return new Promise(resolve=>{release=resolve})
    return {state:'ready',generation:1,binding:{version_id:'v',files:{}},package:structuredClone(pack)}
  })
  t.mock.method(api,'select',async()=>({}))
  const old=state.refreshCurrent();await state.save()
  release({state:'unbound',generation:0,binding:null});await old
  assert.equal(state.current.generation,1);assert.match(state.notice,/已保存并核实/);assert.equal(state.error,'')
})
