<script setup>
import { computed, nextTick, onUnmounted, ref, shallowRef, watch } from 'vue'
import { ArrowLeft, PanelLeft } from '@lucide/vue'
import CapabilityPreview from './CapabilityPreview.vue'
import ThemeBlockFrame from './ThemeBlockFrame.vue'
import ThemeObjectDetail from './ThemeObjectDetail.vue'
import { themeComponentRegistry } from './registry'
import { createContextGate, validateComponentInput, validateLoadedPackage, validateNavigation, validateResource, validateSourceRevision } from './contract'

const props = defineProps({ themePackage: { type: Object, required: true }, projectId: { type: String, required: true }, projectLabel: { type: String, default: '' }, userId: { type: String, required: true }, bindingGeneration: { type: Number, default: 0 }, adapter: { type: Object, required: true }, paused: { type: Boolean, default: false }, simulation: { type: Boolean, default: false }, initialContext: { type: Object, default: null }, openBusiness: { type: Function, default: null } })
const emit = defineEmits(['context-invalid'])
const pack = shallowRef(null), definitionError = ref(''), pageId = ref(''), selectedTopicId = ref('')
const results = shallowRef({}), queries = ref({}), detail = shallowRef(null), detailEvent = ref(null)
const content = ref(null), mobileOpen = ref(false), navigationError = ref('')
const gate = createContextGate()
let pendingRestore = null
let controller, scopeKey = '', knownTopics = [], returnContext = null
const page = computed(() => pack.value?.theme.pages.find(item => item.id === pageId.value))
const regions = computed(() => page.value?.layout === 'reading' ? ['summary', 'aside', 'main'] : ['summary', 'main', 'aside'])
const resourceIndex = computed(() => (page.value?.blocks || []).filter(block => ['json', 'image'].includes(block.type)).map(block => ({ title: block.title, ...block.binding, mediaType: block.binding.kind === 'file' ? pack.value.manifest.files[block.binding.alias] : pack.value.manifest.assets[block.binding.alias].mediaType })))
const projectName = computed(() => props.projectLabel || Object.values(results.value).find(result => result.value?.project)?.value.project.name || '当前项目')
const snapshot = () => ({ userId: props.userId, projectId: props.projectId, packageRef: pack.value.reference, digest: pack.value.digest, bindingGeneration: props.bindingGeneration, pageId: pageId.value, selectedTopicId: selectedTopicId.value })
const queryKey = (block, id = pageId.value) => JSON.stringify([id, block.id])
const cancel = () => { gate.invalidate(); controller?.abort() }

/** 接收适配器结果，所有字节与DTO在进入组件前完成校验。 */
async function receive(response, block, context) {
  if (!['ready', 'empty', 'unbound', 'missing', 'denied', 'error'].includes(response?.state)) throw new Error('适配器返回不支持的状态')
  if (!['ready', 'empty'].includes(response.state)) return { state: response.state, message: response.message }
  if (['json', 'image'].includes(block.type)) {
    if (response.state !== 'ready') throw new Error('文件读取不能以空业务集合表示')
    const resource = await validateResource(response, block.type === 'json' ? 'application/json' : 'image/png')
    const expected = block.binding.kind === 'asset' ? pack.value.manifest.assets[block.binding.alias]?.sha256 : resource.metadata.sha256
    if (resource.metadata.sha256 !== expected) throw new Error('包内资源与manifest指纹不一致')
    return { state: 'ready', ...resource, ...(block.type === 'json' ? { value: JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(resource.bytes)) } : {}) }
  }
  const value = validateComponentInput(block.binding.resource, response.value, { ...context, scope: block.binding.scope })
  if (response.state === 'empty' && (!Array.isArray(value) || value.length)) throw new Error('空状态与业务集合不一致')
  const related = {}
  for (const [resource, items] of Object.entries(response.related || {})) related[resource] = validateComponentInput(resource, items, context)
  const contextTopic = response.contextTopic ? validateComponentInput('selectedTopic', response.contextTopic, context) : undefined
  return { state: response.state, value, related, contextTopic, pagination: response.pagination, relatedCounts: response.relatedCounts }
}

/** 整页共享一次上下文token；只在相同授权范围的查询刷新保留上次列表。 */
async function loadPage(retain = false) {
  cancel()
  if (!page.value || props.paused || definitionError.value) return
  controller = new AbortController()
  const token = gate.next(snapshot()), signal = controller.signal
  const blocks = page.value.blocks
  const previous = results.value
  const stableScope = scopeKey === JSON.stringify([token.userId, token.projectId, token.digest, token.bindingGeneration, token.packageRef])
  results.value = Object.fromEntries(blocks.map(block => {
    const old = previous[block.id]
    const keepSelector = stableScope && block.type === 'records' && ['selector', 'compactSelector'].includes(block.variant)
    return [block.id, keepSelector && old?.state === 'ready' ? old : { state: 'loading', previous: retain && old?.state === 'ready' ? old : undefined }]
  }))
  scopeKey = JSON.stringify([token.userId, token.projectId, token.digest, token.bindingGeneration, token.packageRef])
  const requests = new Map()
  await Promise.all(blocks.map(async block => {
    try {
      const query = { offset: 0, limit: 20, search: '', progress: '', ...queries.value[queryKey(block, token.pageId)], statuses: block.statuses || [] }
      const key = JSON.stringify([block.binding, query])
      if (!requests.has(key)) requests.set(key, props.adapter.read(block.binding, { ...token, query }, signal))
      const response = await requests.get(key)
      if (!gate.isCurrent(token)) return
      const result = await receive(response, block, token)
      if (!gate.isCurrent(token)) return
      results.value = { ...results.value, [block.id]: result }
      if (block.binding.resource === 'topics' && ['ready', 'empty'].includes(result.state)) {
        knownTopics = result.value.map(item => item.id)
        if (!selectedTopicId.value) selectedTopicId.value = knownTopics[0] || ''
      }
    } catch (cause) {
      if (gate.isCurrent(token) && cause.contextInvalid) { cancel(); results.value = {}; knownTopics = []; selectedTopicId.value = ''; emit('context-invalid', cause.message); return }
      if (gate.isCurrent(token)) results.value = { ...results.value, [block.id]: { state: 'error', message: cause.message || '读取失败' } }
    }
  }))
  await nextTick()
  if (pendingRestore && gate.isCurrent(token) && content.value) {
    content.value.scrollTop = pendingRestore.top || 0
    Array.from(content.value.querySelectorAll('[data-object-key]')).find(node => node.dataset.objectKey === pendingRestore.focusKey)?.focus({ preventScroll: true })
    pendingRestore = null
  }
  return token
}

/** 对象宿主重新核对类型、身份及项目，再展示准确详情。 */
async function openObject(event) {
  cancel()
  if (!returnContext) returnContext = { pageId: pageId.value, selectedTopicId: selectedTopicId.value, queries: Object.fromEntries(Object.entries(queries.value).map(([key, query]) => [key, { ...query }])), top: content.value?.scrollTop || 0, focusKey: `${event.objectType}:${event.id}`, scope: scopeKey }
  detailEvent.value = event
  detail.value = { state: 'loading' }
  controller = new AbortController()
  const token = gate.next(snapshot())
  try {
    const response = await props.adapter.readObject(event, token, controller.signal)
    if (!gate.isCurrent(token)) return
    if (response.state !== 'ready') {
      if (!['missing', 'denied', 'error'].includes(response.state)) throw new Error('对象详情返回不支持的状态')
      detail.value = response
      return
    }
    const resource = { topic: 'topics', decision: 'decisions', workTask: 'workTasks' }[event.objectType]
    const value = validateComponentInput(resource, [response.value], token)[0]
    if (value.id !== event.id) throw new Error('详情对象与请求身份不一致')
    const related = {}
    for (const [name, items] of Object.entries(response.related || {})) related[name] = validateComponentInput(name, items, token)
    if ((related.topics || []).some(item => item.id !== value.topic_id) || (related.decisions || []).some(item => item.id !== value.source_decision_id)) throw new Error('详情关联对象与来源引用不一致')
    const sourceRevision = response.sourceRevision ? validateSourceRevision(response.sourceRevision, value) : null
    if (props.openBusiness) { props.openBusiness(event, { ...returnContext, ...snapshot() }); return }
    detail.value = { ...response, value, related, sourceRevision }
    await nextTick()
    if (gate.isCurrent(token)) { content.value.scrollTop = 0; content.value.querySelector('[data-return]')?.focus({ preventScroll: true }) }
  } catch (cause) { if (gate.isCurrent(token) && cause.contextInvalid) { cancel(); results.value = {}; detail.value = null; detailEvent.value = null; emit('context-invalid', cause.message) } else if (gate.isCurrent(token)) detail.value = { state: 'error', message: cause.message } }
}

/** 返回原页只接受宿主捕获的上下文，不解析返回URL。 */
async function returnToPage() {
  cancel()
  const source = returnContext
  detail.value = null; detailEvent.value = null; returnContext = null
  if (!source || source.scope !== scopeKey) return
  pageId.value = source.pageId; selectedTopicId.value = source.selectedTopicId; queries.value = source.queries
  const token = await loadPage(true)
  await nextTick()
  if (content.value && token && gate.isCurrent(token)) {
    content.value.scrollTop = source.top
    Array.from(content.value.querySelectorAll('[data-object-key]')).find(node => node.dataset.objectKey === source.focusKey)?.focus({ preventScroll: true })
  }
}

/** 可信导航入口统一验证，未知页面或选择明确失败。 */
async function navigate(value) {
  try {
    const event = validateNavigation({ ...value })
    navigationError.value = ''
    if (event.kind === 'page') {
      if (!pack.value.theme.pages.some(item => item.id === event.pageId)) throw new Error('当前主题没有此页面')
      cancel()
      detail.value = null; detailEvent.value = null; returnContext = null
      const samePage = pageId.value === event.pageId
      pageId.value = event.pageId; mobileOpen.value = false
      if (samePage) void loadPage()
      await nextTick(); content.value.scrollTop = 0; content.value.querySelector('h1')?.focus({ preventScroll: true })
    } else if (event.kind === 'selectTopic') {
      if (!knownTopics.includes(event.id)) throw new Error('议题不在当前已读取的项目集合中')
      selectedTopicId.value = event.id
    } else await openObject(event)
  } catch (cause) { navigationError.value = cause.message }
}
function changeQuery(block, query) { queries.value = { ...queries.value, [queryKey(block)]: { ...query } }; void loadPage(true) }

/** 注册组件只接收其实际消费的输入，不把宿主属性透传到DOM。 */
function componentProps(block) {
  const input = { result: results.value[block.id]?.previous || results.value[block.id] }
  if (['summary', 'records', 'image'].includes(block.type)) input.block = block
  if (['records', 'topic', 'discussion'].includes(block.type)) input.topicLabel = pack.value.theme.topicLabel
  if (block.type === 'discussion') input.query = queries.value[queryKey(block)] || { offset: 0, limit: 20 }
  if (block.type === 'records') Object.assign(input, { selectedTopicId: selectedTopicId.value, resourceIndex: resourceIndex.value, query: queries.value[queryKey(block)] || { offset: 0, limit: 20, search: '', progress: '' } })
  return input
}

/** 事件由可信组件声明，主题不能注入自定义事件处理器。 */
function componentEvents(block) {
  const events = {}
  if (['records', 'topic', 'discussion'].includes(block.type)) events.navigate = navigate
  if (['records', 'discussion'].includes(block.type)) events.query = value => changeQuery(block, value)
  if (block.type === 'image') events.retry = () => loadPage()
  return events
}

watch(() => [props.themePackage, props.projectId, props.userId, props.bindingGeneration, props.adapter], () => {
  cancel(); pendingRestore = null; definitionError.value = ''; detail.value = null; detailEvent.value = null; returnContext = null
  const sameProject = scopeKey && JSON.parse(scopeKey)[0] === props.userId && JSON.parse(scopeKey)[1] === props.projectId
  const samePackage = sameProject && JSON.parse(scopeKey)[2] === props.themePackage.digest && JSON.parse(scopeKey)[4] === props.themePackage.reference
  const sameSelection = samePackage && JSON.parse(scopeKey)[3] === props.bindingGeneration
  const previousPage = pageId.value
  const previousQueries = queries.value
  if (!sameSelection) selectedTopicId.value = ''
  knownTopics = []; results.value = {}; queries.value = sameSelection ? previousQueries : {}; scopeKey = ''
  try {
    pack.value = validateLoadedPackage(props.themePackage)
    pageId.value = sameSelection && pack.value.theme.pages.some(item => item.id === previousPage) ? previousPage : pack.value.theme.pages[0].id
    const initial = props.initialContext
    if (initial && initial.userId === props.userId && initial.projectId === props.projectId && initial.packageRef === pack.value.reference && initial.digest === pack.value.digest && initial.bindingGeneration === props.bindingGeneration && pack.value.theme.pages.some(item => item.id === initial.pageId)) {
      pageId.value = initial.pageId; selectedTopicId.value = initial.selectedTopicId || ''; queries.value = initial.queries || {}; pendingRestore = initial
    }
    void loadPage()
  } catch (cause) { pack.value = null; definitionError.value = cause.message }
}, { immediate: true })
watch(selectedTopicId, (next, previous) => {
  if (!previous || next === previous) return
  for (const current of pack.value?.theme.pages || []) for (const block of current.blocks) {
    if (block.binding.resource === 'discussions' || block.binding.scope === 'selectedTopic') {
      const key = queryKey(block, current.id)
      if (queries.value[key]) queries.value[key] = { ...queries.value[key], offset: 0 }
    }
  }
}, { flush: 'sync' })
watch([pageId, selectedTopicId, () => props.paused], () => {
  if (props.paused) { cancel(); results.value = {}; return }
  if (!detailEvent.value) void loadPage()
}, { flush: 'sync' })
onUnmounted(cancel)
/** 原办理离开或显式刷新都捕获当前宿主上下文，数据仍在返回后重读。 */
function captureContext() {
  if (!pack.value) return null
  return { ...snapshot(), queries: Object.fromEntries(Object.entries(queries.value).map(([key, query]) => [key, { ...query }])), top: content.value?.scrollTop || 0, focusKey: returnContext?.focusKey || '' }
}
defineExpose({ navigate, selectedTopicId, pageId, captureContext })
</script>

<template>
  <section class="theme-host">
    <div v-if="definitionError" class="theme-definition-error" role="alert"><h2>主题定义不受支持</h2><p>{{ definitionError }}</p><p>请返回主题预览选择其他包；不会自动启用默认主题。</p></div>
    <template v-else-if="pack && page">
      <nav class="theme-page-navigation" aria-label="项目主题页面"><button class="theme-mobile-menu" :aria-expanded="mobileOpen" @click="mobileOpen = !mobileOpen"><PanelLeft :size="18" />主题导航</button><div :class="{ open: mobileOpen }"><small>主题页面</small><button v-for="item in pack.theme.pages.filter(item => !pack.theme.hiddenCapabilities.includes(item.capability))" :key="item.id" :aria-current="pageId === item.id ? 'page' : undefined" @click="navigate({ kind: 'page', pageId: item.id })">{{ item.title }}</button><slot name="platform-navigation" /></div></nav>
      <main ref="content" class="theme-content">
        <p v-if="navigationError" class="theme-state error" role="alert">{{ navigationError }}</p>
        <template v-if="detailEvent"><button data-return class="theme-back" @click="returnToPage"><ArrowLeft :size="16" />返回 {{ page.title }}</button><ThemeObjectDetail v-if="detail?.state === 'ready'" :result="detail" :object-type="detailEvent.objectType" :project-name="projectName" :simulation="simulation" @navigate="navigate" /><ThemeBlockFrame v-else :block="{ id: 'object-detail', title: '对象详情' }" :result="detail || { state: 'loading' }" @retry="openObject(detailEvent)" /></template>
        <template v-else>
          <header class="theme-intro"><small>{{ pack.theme.name }} / {{ projectName }}</small><h1 tabindex="-1">{{ page.title }}</h1><p>{{ page.description }}</p></header>
          <CapabilityPreview v-if="page.capability" :capability="page.capability" :topic-label="pack.theme.topicLabel" :presentation="pack.theme.presentation" />
          <div v-else class="theme-page-grid" :class="[page.layout, { 'has-summary': page.blocks.some(block => block.region === 'summary') }]">
            <div v-for="region in regions" :key="region" :class="`theme-region-${region}`">
              <ThemeBlockFrame v-for="block in page.blocks.filter(item => item.region === region)" :key="block.id" :block="block" :result="results[block.id] || { state: 'loading' }" @navigate="navigate" @retry="loadPage">
                <component :is="themeComponentRegistry[block.type]" v-bind="componentProps(block)" v-on="componentEvents(block)" />
              </ThemeBlockFrame>
            </div>
          </div>
        </template>
      </main>
    </template>
  </section>
</template>
<style lang="less" src="./theme.less"></style>
