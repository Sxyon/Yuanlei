import assert from 'node:assert/strict'
import { before, after, test } from 'node:test'
import { createServer } from 'vite'
import { createSSRApp, h, ref, createRenderer, getCurrentInstance, nextTick, ssrContextKey } from 'vue'
import { setImmediate } from 'node:timers'
import { renderToString } from 'vue/server-renderer'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
let vite, Overview, Manager, api
before(async () => {
  globalThis.localStorage = {getItem:()=>null,setItem(){},removeItem(){}}
  vite = await createServer({server:{middlewareMode:true,hmr:false},appType:'custom'})
  ;({default:Overview}=await vite.ssrLoadModule('/src/components/project/capabilities/ThemedOverview.vue'))
  ;({default:Manager}=await vite.ssrLoadModule('/src/components/project/ProjectThemeManager.vue'))
  ;({projectThemeApi:api}=await vite.ssrLoadModule('/src/apis/project_theme_api.js'))
  globalThis.window={matchMedia:()=>({matches:false,addEventListener(){},removeEventListener(){}}),addEventListener(){},removeEventListener(){}}
  globalThis.document={addEventListener(){},removeEventListener(){},documentElement:{classList:{add(){},remove(){}}}}
})
after(async () => {await vite?.close();delete globalThis.localStorage;delete globalThis.document;delete globalThis.window})
async function render(component, props, provide = {}) {
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects/:project_id/dashboard',name:'ProjectDashboardComp',component:{render:()=>null}},{path:'/projects/:project_id/inspection',name:'ProjectInspectionBoardComp',component:{render:()=>null}},{path:'/',name:'ProjectsComp',component:{render:()=>null}},{path:'/projects/:project_id/blueprints',name:'ProjectBlueprints',component:{render:()=>null}},{path:'/projects/:project_id/topics',name:'ProjectTopics',component:{render:()=>null}}]})
  await router.push('/')
  const app=createSSRApp({render:()=>h(component,props)});app.use(createPinia());app.use(router)
  app.component('a-popover',{setup:(_, {slots})=>()=>h('div',slots.default?.())})
  app.component('a-button',{setup:(_, {slots,attrs})=>()=>h('button',attrs,slots.default?.())})
  for(const [key,value] of Object.entries(provide))app.provide(key,value)
  return renderToString(app)
}
test('精简总览仅蓝图与最近动态；调研使用课题正文与真实决定空态',async()=>{
  const props={projectId:'p',presentation:'focus',blueprint:{name:'方向.md',content:'# 正式蓝图\n\n现有正文'},topics:[{id:'t1',title:'现有问题',summary:'原问题正文',expected_outcome:'原预期结果'}],decisions:[],activity:[{event_key:'event',id:'t1',kind:'topic',title:'现有动态',author_name:'作者',created_at:'2026-10-16'}]}
  const focus=await render(Overview,props)
  assert.match(focus,/data-overview-presentation="focus"/);assert.match(focus,/正式蓝图/);assert.match(focus,/最近动态/)
  assert.equal((focus.match(/<section /g)||[]).length,2)
  assert.doesNotMatch(focus,/需要你处理|当前推进|课题目录/)
  const research=await render(Overview,{...props,presentation:'research'},{projectThemeContext:ref({package:{theme:{topicLabel:'课题'}}})})
  assert.match(research,/课题目录/);assert.match(research,/现有问题/);assert.match(research,/暂无已记录决定/)
  assert.doesNotMatch(research,/采用两周|已批准/)
  const empty=await render(Overview,{presentation:'focus',projectId:'p'})
  assert.match(empty,/还没有项目蓝图/);assert.match(empty,/还没有最近动态/)
})
test('真实总览装配消费主题上下文；管理页收起帮助并去掉历史与手动刷新入口',async t=>{
  t.mock.method(api,'catalog',async()=>({sources:[]}))
  const manager=await render(Manager,{projectId:'',projects:[]})
  assert.match(manager,/主题管理帮助/);assert.match(manager,/项目主题设置/)
  assert.doesNotMatch(manager,/S03 合成样例|返回项目列表|刷新目录|主题维护 · 候选|选择项目并分配主题|项目分配/)
  const {default:Assembled}=await vite.ssrLoadModule('/src/components/project/capabilities/OverviewWorkspace.vue')
  const {governanceBoardApi}=await vite.ssrLoadModule('/src/apis/governance_board_api.js')
  for(const name of ['getProjectBoard','listTopics','recentActivity','listBlueprints','listDecisions'])t.mock.method(governanceBoardApi,name,async()=>name==='recentActivity'?{items:[]}:name==='listBlueprints'?{documents:[]}:[])
  const page=await render(Assembled,{projectId:'p'},{projectThemeContext:ref({scope:'p:version:2',package:{theme:{presentation:'focus'}}})})
  assert.match(page,/data-overview-presentation="focus"/)
  assert.doesNotMatch(page,/需要你处理|当前推进|Git/)
})


test('自动核对目录保留候选草稿，迟到目录不覆盖最新读取；发布后回读目录',async t=>{
  const renderer=createRenderer({createElement:()=>({}),createText:()=>({}),createComment:()=>({}),insert(){},remove(){},setText(){},setElementText(){},patchProp(){},parentNode:()=>null,nextSibling:()=>null})
  const source={id:'s',kind:'personal',name:'个人',status:'active',versions:[],candidate_revision:1}
  const pack={manifest:{},theme:{id:'test'}}
  t.mock.method(api,'catalog',async()=>({sources:[source]}))
  const pinia=createPinia();setActivePinia(pinia)
  const router=createRouter({history:createMemoryHistory(),routes:[{path:'/projects/:project_id/dashboard',name:'ProjectDashboardComp',component:{render:()=>null}},{path:'/projects/:project_id/inspection',name:'ProjectInspectionBoardComp',component:{render:()=>null}},{path:'/',name:'ProjectsComp',component:{render:()=>null}}]});await router.push('/')
  let instance
  const Host={...Manager,render(){instance=getCurrentInstance();return h('div')}}
  const app=renderer.createApp({render:()=>h(Host,{projectId:'',projects:[]})});app.use(pinia);app.use(router);app.provide(ssrContextKey,{modules:new Set()});app.mount({});t.after(()=>app.unmount())
  await nextTick();await new Promise(resolve=>setImmediate(resolve));await nextTick()
  const state=instance.setupState
  const racing=[];t.mock.method(api,'catalog',()=>new Promise(resolve=>racing.push(resolve)))
  const initial=state.load(),newer=state.refreshCatalog()
  racing[1]({sources:[{...source,name:'切换后的目录'}]});await newer
  racing[0]({sources:[{...source,name:'迟到初始目录'}]});await initial
  assert.equal(state.sources[0].name,'切换后的目录')
  const late=[];let release
  t.mock.method(api,'catalog',()=>late.length<2 ? new Promise((resolve,reject)=>late.push({resolve,reject})) : Promise.resolve({sources:[{...source,name:'核实的新目录'}]}))
  const failedInitial=state.load()
  const activeRun=state.run(async()=>{await state.refreshCatalog();await new Promise(resolve=>{release=resolve})})
  late[1].resolve({sources:[{...source,name:'核实的新目录'}]})
  await nextTick();await new Promise(resolve=>setImmediate(resolve))
  late[0].reject(new Error('迟到目录错误'));await failedInitial
  assert.equal(state.error,'');assert.equal(state.busy,true);assert.equal(state.sources[0].name,'核实的新目录')
  release();await activeRun;assert.equal(state.busy,false)
  state.activeId='s';state.candidate={source,package:pack};state.definition='草稿保留'
  const pending=[];t.mock.method(api,'catalog',()=>new Promise(resolve=>pending.push(resolve)))
  const first=state.refreshCatalog(),second=state.refreshCatalog()
  pending[1]({sources:[{...source,name:'最新'}]});await second
  pending[0]({sources:[{...source,name:'旧目录'}]});await first
  assert.equal(state.sources[0].name,'最新');assert.equal(state.definition,'草稿保留');assert.equal(state.dirty,true)
  state.definition=JSON.stringify(pack)
  t.mock.method(api,'publish',async()=>({id:'v',version:'3'}))
  let reads=0;t.mock.method(api,'catalog',async()=>{reads++;return {sources:[{...source,name:'服务端回读',versions:[{id:'v',version:'3'}]}]}})
  await state.run(state.publish)
  state.candidate=null;await state.assignVersion('v');assert.equal(state.selectionOpen,true);assert.equal(state.selectionVersionId,'v')
  state.selectionRef={canDiscard:async()=>false};await state.closeSelection();assert.equal(state.selectionOpen,true)
  state.selectionRef={canDiscard:async()=>true};await state.closeSelection();assert.equal(state.selectionOpen,false)
  assert.equal(reads,1);assert.equal(state.sources[0].name,'服务端回读');assert.equal(state.sources[0].versions[0].id,'v')
})


test('真实项目宿主导航消费隐藏配置，移除宿主接线会重新暴露六项能力',async t=>{
  const {default:Layout}=await vite.ssrLoadModule('/src/layouts/ProjectLayout.vue')
  const {useProjectsStore}=await vite.ssrLoadModule('/src/stores/projects.js')
  const {useUserStore}=await vite.ssrLoadModule('/src/stores/user.js')
  const {baseWorkspacePages}=await import('../../src/components/project/themes/workspaceCapabilities.js')
  const pinia=createPinia();setActivePinia(pinia);useUserStore().uid='u'
  const store=useProjectsStore();store.projects=[{id:'p',name:'P'}];store.hasLoaded=true;t.mock.method(store,'loadProjects',async()=>{})
  const pack={manifest:{formatVersion:1,componentAbi:3,theme:'theme.json',source:'test',files:{},assets:{}},theme:{id:'focus',version:'3',name:'精简',topicLabel:'议题',baseVersion:1,presentation:'focus',hiddenCapabilities:['plans','work','inspection','files','agents','settings'],pages:[{id:'home',title:'总览',description:'项目',layout:'overview',capability:'overview',blocks:[]}]},reference:'v',digest:'a'.repeat(64)}
  t.mock.method(api,'binding',async()=>({state:'ready',generation:4,binding:{version_id:'v'},package:pack}))
  const router=createRouter({history:createMemoryHistory(),routes:[...baseWorkspacePages.map(page=>({path:'/projects/:project_id/'+page.capability,name:page.route,component:{render:()=>null}})),{path:'/projects',name:'ProjectsComp',component:{render:()=>null}}]});await router.push('/projects/p/overview')
  const Host={...Layout,async setup(props,context){const state=Layout.setup(props,context);await nextTick();await new Promise(resolve=>setImmediate(resolve));return state}}
  const app=createSSRApp({render:()=>h(Host)});app.use(pinia);app.use(router)
  const html=await renderToString(app)
  const nav=html.match(/<nav[^>]*aria-label="项目工作空间导航"[\s\S]*?<\/nav>/)?.[0]
  assert.ok(nav,html);assert.doesNotMatch(nav,/主题选择[／/]恢复/)
  for(const visible of ['总览','蓝图','议题'])assert.match(nav,new RegExp('>'+visible+'<'))
  for(const hidden of ['行动计划','工作','督查','资料','智能体','设置'])assert.doesNotMatch(nav,new RegExp('>'+hidden+'<'))
  assert.match(html,/data-theme-version="v"/);assert.match(html,/data-theme-generation="4"/)
})

test('未绑定或当前包损坏不遮蔽准确混合资料页真实预览',async t=>{
  const {default:Panel}=await vite.ssrLoadModule('/src/components/project/ProjectThemePanel.vue')
  const pack={manifest:{formatVersion:1,componentAbi:3,theme:'theme.json',source:'fixture',files:{facts:'application/json'},assets:{}},theme:{id:'independent',version:'3',name:'真实混合资料',topicLabel:'课题',baseVersion:1,pages:[{id:'evidence',title:'项目证据',description:'项目级',layout:'full',blocks:[{id:'facts',type:'json',title:'真实资料',region:'main',binding:{kind:'file',alias:'facts'}}]},{id:'home',title:'总览',description:'项目总览',layout:'overview',capability:'overview',blocks:[]}]},reference:'v',digest:'a'.repeat(64)}
  t.mock.method(api,'binding',async()=>({state:'unbound',generation:0}))
  t.mock.method(api,'previewFile',async()=>({state:'unbound',message:'未绑定'}))
  for(const state of ['unbound','error']) {
    const html=await render(Panel,{projectId:'p'},{projectThemeContext:ref({package:pack,preview:{versionId:'v',files:{}},selection:{state,generation:0},error:'旧绑定不可用',loading:false})})
    assert.match(html,/class="theme-host/)
    assert.match(html,/项目证据/)
    assert.doesNotMatch(html,/原项目绑定保留/)
  }
  const saved=await render(Panel,{projectId:'p'},{projectThemeContext:ref({package:null,preview:null,selection:{state:'error',generation:1},error:'旧绑定不可用',loading:false})})
  assert.doesNotMatch(saved,/class="theme-host/)
})

test('资料块到能力页的动作保留准确预览引用并进入真实项目路由',async()=>{
  const {default:Panel}=await vite.ssrLoadModule('/src/components/project/ProjectThemePanel.vue')
  const pack={manifest:{},theme:{name:'混合',version:'3',pages:[{id:'body',title:'课题',capability:'topics'}]}}
  let state
  const Captured={...Panel,setup(props,context){state=Panel.setup(props,context);return state}}
  await render(Captured,{projectId:'p'},{projectThemeContext:ref({package:pack,selection:{state:'ready',generation:2},preview:{sourceId:'source',revision:4,files:{facts:'/facts.json'}},loading:true})})
  await state.openPage('body')
  assert.equal(state.router.currentRoute.value.name,'ProjectTopics')
  assert.deepEqual(state.router.currentRoute.value.query,{theme_preview_source:'source',theme_preview_revision:'4',theme_preview_files:'{"facts":"/facts.json"}',theme_page:'body'})
})
