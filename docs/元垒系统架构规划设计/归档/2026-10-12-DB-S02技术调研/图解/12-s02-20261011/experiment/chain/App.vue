<script setup>
import { computed, ref, onMounted } from 'vue'
import ThemeBlock from './ThemeBlock.vue'
import '../chain/style.css'
const registry = Object.fromEntries(['summary','records','json','image','html','markdown'].map(key=>[key,ThemeBlock]))
const env = ref('A'), selected = ref(null), catalog = ref([]), system = ref(null), resources = ref({}), pageId = ref(''), host = ref(null), error = ref(''), loading = ref(false)
const theme = computed(()=>selected.value?.theme)
const page = computed(()=>theme.value?.pages.find(item=>item.id===pageId.value))
const project = computed(()=>env.value.toLowerCase()+'-energy')
let sequence = 0
const imageUrls = []
/** 宿主固定环境身份及项目，主题不能提供请求URL。 */
async function api(path, options={}, scope={env:env.value,project:project.value}) {
  const response = await fetch('/'+scope.env+'/_chain/'+scope.project+'/'+path,{...options,headers:{'X-Lab-Actor':'lab-user-'+scope.env.toLowerCase(),'Content-Type':'application/json'}})
  if(!response.ok) throw Error((await response.json()).detail)
  return response
}
/** 读取持久绑定后才组装可信组件，迟到响应不得串环境。 */
async function load() {
  const current=++sequence, scope={env:env.value,project:project.value}
  loading.value=true;error.value='';selected.value=null;system.value=null;resources.value={};host.value=null
  imageUrls.splice(0).forEach(url=>URL.revokeObjectURL(url))
  try {
    const entries=await (await api('catalog',{},scope)).json()
    if(current!==sequence)return
    const chosen=await (await api('theme',{},scope)).json()
    if(current!==sequence)return
    const data=await (await api('system',{},scope)).json()
    const files={}
    for(const alias of Object.keys(chosen.manifest.files)) {
      if(current!==sequence)return
      const response=await api('file/'+alias+'?generation='+chosen.generation,{},scope)
      if(alias==='image') {const url=URL.createObjectURL(await response.blob());files[alias]=url;imageUrls.push(url)}
      else files[alias]=await response.text()
    }
    if(current!==sequence)return
    selected.value=chosen;catalog.value=entries;system.value=data;resources.value=files;pageId.value=chosen.theme.pages[0].id
  } catch(failure){if(current===sequence)error.value=String(failure.message)}
  finally{if(current===sequence)loading.value=false}
}
/** 合成环境目标文件由宿主选择，映射不属于可携主题。 */
async function activate(entry) {
  const scope={env:env.value,project:project.value}
  const prefix=scope.env==='A'?'/evidence/':'/different-location/'
  try { await api('selection',{method:'PUT',body:JSON.stringify({digest:entry.digest,expectedGeneration:selected.value.generation,files:{metrics:prefix+'metrics.json',image:prefix+'sample.png',report:prefix+'report.html',notes:prefix+'notes.md'}})},scope)
  if(scope.env===env.value)await load()
  } catch(failure){if(scope.env===env.value)error.value=String(failure.message)}
}
/** 已读对象进入合成宿主详情，保留原页。 */
function openObject(binding,id){if(!system.value?.[binding]?.some(item=>item.id===id)){error.value='object_scope_denied';return}host.value={binding,id}}
function changeEnv(value){env.value=value;void load()}
onMounted(load)
</script>
<template>
<div class="lab"><aside class="platform"><div class="brand">元垒<small>S02 CHAIN</small></div><div class="platform-item active">项目</div><p>真实HTTP / PG<br>独立A/B文件域<br>身份与业务模拟</p></aside><main>
<header><div><span class="eyebrow">DB-S02 · 全链路可行性 R3</span><h1>主题加载、保存与迁移试验</h1></div><span class="badge">隔离技术试验 · 未接入产品</span></header>
<section class="project-bar"><div><strong>{{system?.project.name||'读取目标环境…'}}</strong><span>{{project}} · 项目与资源在目标环境重新绑定</span></div><div class="theme-controls"><button :aria-pressed="env==='A'" @click="changeEnv('A')">环境 A</button><button :aria-pressed="env==='B'" @click="changeEnv('B')">环境 B</button><button @click="load">重新加载</button></div></section>
<div v-if="loading" role="status">读取数据库选择、校验包与目标文件…</div><div v-if="error" role="alert">{{error}} · 宿主项目入口保留</div>
<template v-if="selected&&!loading"><section class="version-bar"><strong>持久选择：{{theme.name}} {{theme.version}}</strong><span>generation {{selected.generation}} · SHA-256 {{selected.digest}}</span><div class="theme-controls"><button v-for="entry in catalog.filter(e=>e.version==='0.1-lab')" :key="entry.digest" :aria-pressed="entry.digest===selected.digest" @click="activate(entry)">{{entry.theme}} · {{entry.version}}</button><button @click="host={binding:'project',id:project}">返回宿主</button></div></section>
<section v-if="host" class="host"><span class="eyebrow">M1 可信宿主 · 合成详情</span><h2>{{host.binding}} / {{host.id}}</h2><button @click="host=null">返回主题原页面</button></section>
<section v-else class="theme-body" :class="theme.layout"><nav><span class="eyebrow">主题局部导航</span><button v-for="item in theme.pages" :key="item.id" :aria-current="item.id===pageId?'page':undefined" @click="pageId=item.id">{{item.title}}</button><small>显示名：{{theme.topicLabel}}</small></nav><div class="content"><div class="page-heading"><span class="eyebrow">Vue 原生动态组件 · 固定可信注册表</span><h2>{{page.title}}</h2></div><div class="blocks"><component :is="registry[block.type]" v-for="(block,index) in page.blocks" :key="index" :block="block" :system="system" :resources="resources" :open-object="openObject" /></div></div></section>
</template><footer>真实：Vue/Vite、FastAPI/Pydantic、PostgreSQL、ZIP字节、当前Workdir、重启及跨环境导入。模拟：身份认证、业务DTO与办理详情。S03—S06产品实施未启动。</footer>
</main></div>
</template>
