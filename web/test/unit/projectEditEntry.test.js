import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createRenderer, getCurrentInstance, h, nextTick, ssrContextKey } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'
import { message } from 'ant-design-vue'
let vite, View, api, useProjectsStore
before(async()=>{
  globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}}
  vite=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  ;({default:View}=await vite.ssrLoadModule('/src/views/ProjectsView.vue'))
  ;({projectThemeApi:api}=await vite.ssrLoadModule('/src/apis/project_theme_api.js'))
  ;({useProjectsStore}=await vite.ssrLoadModule('/src/stores/projects.js'))
})
after(async()=>{await vite?.close();delete globalThis.localStorage})
const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},patchProp(){},parentNode:()=>null,nextSibling:()=>null})
async function mount(t){
  setActivePinia(createPinia())
  t.mock.method(useProjectsStore(),'loadProjects',async()=>[])
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects',name:'ProjectsComp',component:{}},{path:'/agent',name:'AgentComp',component:{}}]})
  await router.push('/projects');await router.isReady()
  let instance
  const Component={...View,render(){instance=getCurrentInstance();return h('div')}}
  const app=renderer.createApp(Component);app.use(router);app.provide(ssrContextKey,{modules:new Set()});app.mount({});t.after(()=>app.unmount())
  await nextTick()
  return {state:()=>instance.setupState,router}
}
test('无绑定保留原编辑弹窗，损坏绑定显示故障而不静默降级',async t=>{
  const error=t.mock.method(message,'error',()=>{})
  const binding=t.mock.method(api,'binding',async()=>({state:'unbound'}))
  const {state}=await mount(t)
  await state().editProject({id:'p'})
  assert.equal(state().editing.id,'p')
  state().editing=null
  binding.mock.mockImplementation(async()=>({state:'error',error:{message:'主题指纹不一致'}}))
  await state().editProject({id:'p'})
  assert.equal(state().editing,null)
  assert.equal(error.mock.calls[0].arguments[0],'主题指纹不一致')
})
test('离开项目列表后，迟到主题读取不能弹出项目编辑器',async t=>{
  let finish
  t.mock.method(api,'binding',()=>new Promise(resolve=>{finish=resolve}))
  const {state,router}=await mount(t)
  const pending=state().editProject({id:'p'})
  await router.push('/agent')
  finish({state:'unbound'});await pending
  assert.equal(state().editing,null)
})
