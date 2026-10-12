<script setup>
import { computed, ref, onMounted } from 'vue'
import { markRaw } from 'vue'
import { FormKitSchema } from '@formkit/vue'
import ThemeBlock from './ThemeBlock.vue'
import { compilePage } from './schema.mjs'
import { validateDefinition } from '../definition.mjs'
import defaultTheme from '../themes/default.json'
import researchTheme from '../themes/research.json'

const themes = [defaultTheme, researchTheme].map(validateDefinition)
if (new URLSearchParams(location.search).has('literal-probe')) themes[0].pages[0].blocks[0].title = '$get(secret)'
const selected = ref(0), pageId = ref('overview'), host = ref(null), system = ref(null), resources = ref({}), error = ref('')
const theme = computed(() => themes[selected.value])
const page = computed(() => theme.value.pages.find(p => p.id === pageId.value))
const library = { ThemeBlock: markRaw(ThemeBlock) }
const schema = computed(() => compilePage(theme.value, pageId.value, system.value, resources.value, openObject))
/** 用逻辑别名读取实验HTTP边界，并回读资源指纹。 */
async function load() {
  try {
    const response = await fetch('/_lab/system?project=fixture-a')
    if (!response.ok) throw Error('system_load_failed')
    system.value = await response.json()
    for (const alias of ['metrics', 'image', 'report', 'notes']) {
      const result = await fetch('/_lab/file?project=fixture-a&alias=' + alias)
      if (!result.ok) throw Error('file_load_failed:' + alias)
      if (alias === 'image') { const url = URL.createObjectURL(await result.blob()); resources.value[alias] = url }
      else resources.value[alias] = await result.text()
    }
  } catch (failure) { error.value = failure.message }
}
/** 切换实验主题时保留宿主项目，回到该主题首页。 */
function switchTheme(index) { selected.value = index; pageId.value = themes[index].pages[0].id; host.value = null }
/** 宿主只接受已读取的合成业务对象，并保留返回位置。 */
function openObject(binding, id) {
  if (!system.value?.[binding]?.some(item => item.id === id)) { error.value = 'object_scope_denied'; return }
  host.value = { binding, id }
}
onMounted(load)
</script>

<template>
  <div class="lab">
    <aside class="platform"><div class="brand">元垒 <small>S02 LAB</small></div><div class="platform-item">智能体</div><div class="platform-item active">项目</div><div class="platform-item">资料</div><p>独立端口<br>合成数据<br>无真实账号</p></aside>
    <main>
      <header><div><span class="eyebrow">DB-S02 · 复用验证 R2</span><h1>项目主题接入试验</h1></div><span class="badge">实验能力 · 尚未接入产品</span></header>
      <section class="project-bar"><div><strong>{{ system?.project.name || '加载项目…' }}</strong><span>fixture-a · 系统对象身份不随别名改变</span></div><div class="theme-controls"><button v-for="(item,index) in themes" :key="item.id" :aria-pressed="index===selected" @click="switchTheme(index)">{{ item.name }}</button><button @click="host={binding:'project',id:'fixture-a'}">返回宿主</button></div></section>
      <div v-if="error" role="alert">{{ error }}</div>
      <section v-if="host" class="host"><span class="eyebrow">M1 可信宿主 · 合成详情</span><h2>{{ host.binding }} / {{ host.id }}</h2><p>此处代表原业务入口；实验不执行批准、撤销或任务写入。</p><button @click="host=null">返回主题原页面</button></section>
      <section v-else class="theme-body" :class="theme.layout">
        <nav><span class="eyebrow">M2 主题局部导航</span><button v-for="item in theme.pages" :key="item.id" :aria-current="item.id===pageId?'page':undefined" @click="pageId=item.id">{{ item.title }}</button><small>主题 {{ theme.version }}<br>显示名：{{ theme.topicLabel }}</small></nav>
        <div class="content"><div class="page-heading"><span class="eyebrow">M3 真实 FormKitSchema 2.1.2 · 可信 Vue 组件</span><h2>{{ page.title }}</h2><p>{{ theme.layout==='grid'?'以管理状态与待办组织项目。':'以课题脉络、研究资料与论证组织项目。' }}</p></div>
          <div class="blocks"><FormKitSchema :schema="schema" :library="library" /></div>
        </div>
      </section>
      <footer>M4 两类数据仅经宿主读取；M5 原业务操作保留宿主责任。演示切换不代表持久绑定或异环境迁移完成。</footer>
    </main>
  </div>
</template>

<style>
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;color:#1d3444;background:#f4f7f9}button{font:inherit;cursor:pointer;border:1px solid #cdd9df;border-radius:7px;background:white;padding:9px 14px;color:inherit}button:focus-visible{outline:3px solid #0b8894;outline-offset:3px}button[aria-pressed=true],button[aria-current=page]{background:#e0f3f0;color:#096a65;border-color:#85c6bc}.lab{display:flex;min-height:100vh}.platform{width:158px;background:#183544;color:#d3e3e8;padding:28px 18px;flex-shrink:0}.brand{font-size:25px;font-weight:700;margin-bottom:42px}.brand small{display:block;font-size:10px;letter-spacing:2px;color:#8dc1c5;margin-top:5px}.platform-item{padding:12px;margin-bottom:10px}.active{background:#305060;border-radius:7px}.platform p{font-size:12px;line-height:2;color:#9ebbc8;margin-top:50px}main{flex:1;min-width:0;padding:28px 34px}header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}h1{font-size:26px;margin:8px 0}h2{font-size:23px;margin:9px 0}h3{font-size:15px;margin:0 0 20px}.eyebrow{font-size:11px;letter-spacing:1px;color:#6a8290}.badge{font-size:12px;border:1px solid #d9bd7b;background:#fff9e9;padding:8px 12px;border-radius:20px}.project-bar{display:flex;justify-content:space-between;align-items:center;padding:18px 22px;background:white;border:1px solid #dce5e9;border-radius:10px;margin-bottom:24px}.project-bar strong{display:block;font-size:17px}.project-bar span{font-size:12px;color:#718591;display:block;margin-top:6px}.theme-controls{display:flex;gap:8px}.theme-body{display:flex;gap:26px}.theme-body nav{width:170px;flex-shrink:0;display:flex;flex-direction:column;gap:10px;padding-top:13px}.theme-body nav small{font-size:11px;color:#7a8d96;line-height:1.8;margin-top:20px}.content{flex:1;min-width:0}.page-heading{margin-bottom:24px}.page-heading p{font-size:13px;color:#728692}.blocks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}article{background:white;border:1px solid #dbe5e9;border-radius:10px;padding:23px;min-width:0}article.summary{border-top:3px solid #168b81}article p{font-size:14px;line-height:1.8}.big{font-size:23px!important;font-weight:600}ul{list-style:none;padding:0;margin:0}li{display:flex;justify-content:space-between;align-items:center;gap:12px;border-top:1px solid #edf1f3;padding:12px 0}li button{border:0;padding:0;text-align:left;color:#187a83}li span{font-size:11px;color:#8498a2}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.8;background:#f4f7f9;padding:14px}.source{display:block;font-size:10px;color:#8498a2;margin-top:22px}img{max-width:100%;height:170px;object-fit:contain}iframe{width:100%;height:190px;border:1px solid #e4eaed}.reading{flex-direction:column}.reading nav{width:auto;flex-direction:row;align-items:center;border-bottom:1px solid #d8e1e5;padding-bottom:18px}.reading nav small{margin:0 0 0 auto}.reading .content{max-width:1000px}.reading .blocks{grid-template-columns:1fr 1fr}.reading article.markdown{border-left:4px solid #52799d}.host{padding:40px;background:white;border:1px solid #dbe5e9;border-radius:10px}footer{font-size:11px;line-height:1.8;color:#85959e;margin-top:26px}@media(max-width:800px){.platform{width:90px;padding:20px 10px}main{padding:20px}.project-bar,header{align-items:flex-start;gap:14px;flex-direction:column}.theme-controls{flex-wrap:wrap}.theme-body{flex-direction:column}.theme-body nav{width:100%;flex-wrap:wrap;flex-direction:row}.blocks,.reading .blocks{grid-template-columns:1fr}.reading nav small{margin:0}.badge{align-self:flex-start}}
</style>
