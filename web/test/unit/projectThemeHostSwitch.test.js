import assert from 'node:assert/strict'
import {after,before,test} from 'node:test'
import {createRenderer,getCurrentInstance,h,ref,ssrContextKey,nextTick} from 'vue'
import {createRouter,createMemoryHistory} from 'vue-router'
import {createPinia,setActivePinia} from 'pinia'
import {createServer} from 'vite'
import {setImmediate} from 'node:timers'
import {Modal} from 'ant-design-vue'
let vite,Layout,api,useUserStore,useProjectsStore,useEdit
before(async()=>{
  globalThis.window={matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){}}
  globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}}
  globalThis.sessionStorage={getItem:()=>null,setItem(){},removeItem(){}}
  vite=await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  ;({default:Layout}=await vite.ssrLoadModule('/src/layouts/ProjectLayout.vue'))
  ;({projectThemeApi:api}=await vite.ssrLoadModule('/src/apis/project_theme_api.js'))
  ;({useUserStore}=await vite.ssrLoadModule('/src/stores/user.js'))
  ;({useProjectsStore}=await vite.ssrLoadModule('/src/stores/projects.js'))
  ;({useProjectThemeEdit:useEdit}=await vite.ssrLoadModule('/src/composables/useProjectThemeEdit.js'))
  globalThis.document={visibilityState:'visible',addEventListener(){},removeEventListener(){}}
})
after(async()=>{await vite?.close();for(const key of ['window','document','localStorage','sessionStorage'])delete globalThis[key]})
const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},patchProp(){},parentNode:()=>null,nextSibling:()=>null})
const settle=async()=>{await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick()}
const pack={manifest:{formatVersion:1,componentAbi:2,theme:'theme.json',source:'测试',assets:{},files:{}},theme:{id:'research',name:'研究',version:'2',topicLabel:'课题',baseVersion:1,density:'comfortable',accent:'teal',pages:[{id:'new-topics',title:'课题',description:'研究',layout:'reading',capability:'topics',blocks:[]}]},reference:'v',digest:'a'.repeat(64)}
const ready=()=>({state:'ready',generation:1,binding:{version_id:'v',files:{}},package:structuredClone(pack)})
async function mount(t,{url='/projects/p/topics',enabled=true,broken=false}={}) {
  const pinia=createPinia();setActivePinia(pinia);useUserStore().uid='u'
  const projects=useProjectsStore();projects.projects=[{id:'p',name:'P'}];projects.hasLoaded=true;t.mock.method(projects,'loadProjects',async()=>{})
  t.mock.method(api,'binding',async()=>ready())
  const router=createRouter({history:createMemoryHistory(),routes:[
    {path:'/projects/:project_id/topics',name:'ProjectTopics',component:{render:()=>null}},
    {path:'/projects/:project_id/dashboard',name:'ProjectDashboardComp',component:{render:()=>null}},
    {path:'/projects/:project_id/work/tasks/:task_id',name:'ProjectWorkTaskView',component:{render:()=>null}},
    {path:'/projects/:project_id/agents/:agent_slug/workbench',name:'ProjectAgentWorkbenchView',component:{render:()=>null}},
    {path:'/projects/:project_id/files',name:'ProjectFiles',component:{render:()=>null}},
    {path:'/projects/:project_id/plans',name:'ProjectPlans',component:{render:()=>null}},
    {path:'/projects/:project_id/theme',name:'ProjectThemeDisplay',component:{render:()=>null}}
  ]});await router.push(url)
  const draft=ref(''),failures=[];let instance
  const Editor={setup(){useEdit('真实表单',()=> 'p',()=>Boolean(draft.value),()=>draft.value='');return()=>{if(broken)throw new Error('render failed');return h('div')}}}
  const Host={...Layout,render(){instance=getCurrentInstance();return this.renderFailed?null:h(Editor)}}
  const app=renderer.createApp({render:()=>h(Host,{enabled})});app.use(pinia);app.use(router);app.provide(ssrContextKey,{modules:new Set()});app.config.errorHandler=cause=>failures.push(cause)
  app.mount({});t.after(()=>app.unmount());await settle()
  return {state:instance.setupState,router,draft,failures}
}
test('同generation包失效也保护真实登记Owner的草稿，取消保留旧版本',async t=>{
  const {state,draft}=await mount(t);draft.value='未保存正文'
  t.mock.method(Modal,'confirm',options=>{options.onCancel()})
  t.mock.method(api,'binding',async()=>({...ready(),state:'error',package:null,error:{message:'digest'}}))
  await state.loadTheme();assert.equal(state.selection.state,'ready');assert.equal(draft.value,'未保存正文');assert.match(state.themeError,/保留旧版编辑/)
  t.mock.method(Modal,'confirm',options=>{options.onOk()})
  await state.loadTheme();assert.equal(state.selection.state,'error');assert.equal(draft.value,'');assert.equal(state.fallback,true)
})
test('陈旧展示page ID带准确对象时跳真实能力路由并保留历史参数',async t=>{
  const {router}=await mount(t,{url:'/projects/p/theme?theme_page=removed&topic_id=t&revision=3#history'})
  await settle();assert.equal(router.currentRoute.value.name,'ProjectTopics');assert.equal(router.currentRoute.value.query.theme_page,'new-topics');assert.equal(router.currentRoute.value.query.topic_id,'t');assert.equal(router.currentRoute.value.query.revision,'3');assert.equal(router.currentRoute.value.hash,'#history')
})
test('平台后代异常不触发项目故障屏障，项目渲染故障保留显式恢复状态',async t=>{
  const platform=await mount(t,{enabled:false,broken:true});assert.equal(platform.state.renderFailed,false);assert.ok(platform.failures.length)
  const project=await mount(t,{broken:true});assert.equal(project.state.renderFailed,true);assert.match(project.state.renderError,/加载失败/)
})


test('准确工作详情换主题只校正page ID，保留task_id及执行定位',async t=>{
  const {router,state}=await mount(t,{url:'/projects/p/work/tasks/task-1?theme_page=old-work#execution-run'})
  assert.equal(router.currentRoute.value.name,'ProjectWorkTaskView');assert.equal(router.currentRoute.value.params.task_id,'task-1')
  t.mock.method(api,'binding',async()=>({...ready(),generation:2,binding:{version_id:'v2',files:{}}}))
  await state.loadTheme();await settle()
  assert.equal(router.currentRoute.value.name,'ProjectWorkTaskView');assert.equal(router.currentRoute.value.params.task_id,'task-1');assert.equal(router.currentRoute.value.query.theme_page,'work');assert.equal(router.currentRoute.value.hash,'#execution-run')
})


test('智能体、资料与旧计划的现有准确对象入口跨主题保留',async t=>{
  for (const [url,name,key,value] of [
    ['/projects/p/agents/research/workbench?theme_page=old-agent','ProjectAgentWorkbenchView','agent_slug','research'],
    ['/projects/p/files?theme_page=old-files&open=%2Freports%2Fone.md','ProjectFiles','open','/reports/one.md'],
    ['/projects/p/plans?theme_page=old-plans#task-plan-1','ProjectPlans',null,null]
  ]) {
    const {router,state}=await mount(t,{url})
    t.mock.method(api,'binding',async()=>({...ready(),generation:2,binding:{version_id:'v2',files:{}}}))
    await state.loadTheme();await settle()
    assert.equal(router.currentRoute.value.name,name)
    if(key)assert.equal(router.currentRoute.value.params[key] || router.currentRoute.value.query[key],value)
    else assert.equal(router.currentRoute.value.hash,'#task-plan-1')
  }
})


test('聚焦与可见性连续回读共用同一草稿确认，取消不丢输入',async t=>{
  const {state,draft}=await mount(t);draft.value='保留未保存'
  let prompt,count=0
  t.mock.method(Modal,'confirm',options=>{prompt=options;count++})
  t.mock.method(api,'binding',async()=>({...ready(),state:'error',package:null,error:{message:'digest'}}))
  const first=state.loadTheme();await settle();assert.equal(count,1)
  const second=state.loadTheme();await settle();assert.equal(count,1)
  prompt.onCancel();await Promise.all([first,second])
  assert.equal(state.selection.state,'ready');assert.equal(draft.value,'保留未保存')
})
