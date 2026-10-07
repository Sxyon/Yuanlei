<template>
  <section>
    <a-button @click="openPreview">查看本次资料</a-button>
    <p v-if="context && !context.expected_fingerprint">资料选择已变化，请重新预览后执行。</p>
    <a-drawer v-model:open="open" width="min(640px, 100vw)" title="执行资料" :destroy-on-close="false">
      <template v-if="!history">
        <p>工作要求及已选来源默认纳入。业务资料与模型、工具运行配置分开；网页只提供引用。</p>
        <label>议题修订（可选）<a-input-number v-model:value="selection.topic_revision" :min="1" aria-label="资料议题修订" /></label>
        <label>蓝图<a-select v-model:value="selection.blueprints" mode="multiple" aria-label="执行资料蓝图" :options="blueprints.map(x => ({ value: x.name, label: x.name }))" /></label>
        <label>结果<a-select v-model:value="selection.results" mode="multiple" aria-label="执行资料结果" :options="(task.results || []).map(x => ({ value: x.id, label: x.summary.slice(0, 60) }))" /></label>
        <label>附件<a-select v-model:value="selection.attachments" mode="multiple" aria-label="执行资料附件" :options="(task.attachments || []).map(x => ({ value: x.id, label: x.file_name }))" /></label>
        <label>项目文件（每行一个项目内路径）<a-textarea v-model:value="filePaths" aria-label="执行资料文件路径" placeholder="/outputs/report.md" /></label>
        <a-button :loading="busy" @click="preview">刷新资料预览</a-button>
      </template>
      <p v-if="busy">读取资料…</p>
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <p v-if="message">{{ message }}</p>
      <template v-if="snapshot">
        <p>{{ history ? '固化时间' : '预览读取时间' }}：{{ snapshot.captured_at }} · 正文预算 {{ snapshot.text_budget }} 字符</p>
        <article v-for="(item, index) in snapshot.items" :key="index">
          <h3>{{ kindLabel(item.kind) }} · {{ item.locator }}</h3>
          <p>{{ modeLabel(item) }} · {{ item.note }}</p>
          <p v-if="item.revision">{{ item.kind === 'topic' ? '议题修订' : '修订' }} {{ item.revision }}</p>
          <details v-if="item.text"><summary>{{ item.truncated ? '查看资料原文（实际注入内容见下方）' : '查看本次文本' }}</summary><pre>{{ item.text }}</pre></details>
          <label v-if="!history && item.mode === 'direct' && item.kind !== 'requirements'">手动摘录（留空使用资料正文）<a-textarea v-model:value="selection.excerpts[`${item.kind}:${item.locator}`]" aria-label="资料手动摘录" /></label>
          <p v-if="item.hash">{{ item.hash_scope === 'prefix' ? '前缀' : '内容' }}哈希：{{ item.hash }}</p>
        </article>
        <details><summary>查看实际注入正文</summary><pre>{{ snapshot.input_text }}</pre></details>
      </template>
    </a-drawer>
  </section>
</template>
<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { projectWorkExecutionApi } from '@/apis/project_work_execution_api'
import { governanceBoardApi } from '@/apis/governance_board_api'
const props = defineProps({ projectId: String, task: { type: Object, required: true } })
const emit = defineEmits(['context'])
const open = ref(false), history = ref(false), busy = ref(false), error = ref(''), message = ref(''), snapshot = ref(null), context = ref(null), blueprints = ref([]), filePaths = ref('')
const selection = ref({ topic_revision: null, blueprints: [], files: [], attachments: [], results: [], excerpts: {} })
let generation = 0, resetting = false
onBeforeUnmount(() => { generation += 1 })
const kindLabel = kind => ({ requirements: '工作要求', decision: '来源决策', topic: '议题', blueprint: '蓝图', result: '业务结果', file: '项目文件', attachment: '附件', knowledge: '知识库', url: '网页引用' }[kind] || '资料')
const modeLabel = item => item.mode === 'missing' ? '缺失或不可访问' : item.mode === 'reference' ? '按需读取引用' : item.truncated ? '直接正文（截断）' : '直接正文'
watch([() => props.projectId, () => props.task.id], () => {
  resetting = true
  generation += 1; open.value = false; busy.value = false; snapshot.value = null; context.value = null; error.value = ''; filePaths.value = ''; blueprints.value = []
  selection.value = { topic_revision: null, blueprints: [], files: [], attachments: [], results: [], excerpts: {} }
  emit('context', null)
  resetting = false
}, { immediate: true })
watch([selection, filePaths], () => {
  if (resetting) return
  generation += 1; busy.value = false;
  const choices = { ...JSON.parse(JSON.stringify(selection.value)), files: filePaths.value.split('\n').map(x => x.trim()).filter(Boolean) }
  context.value = { selection: choices, expected_fingerprint: null }; emit('context', context.value)
}, { deep: true, flush: 'sync' })
async function preview() {
  const seq = ++generation, project = props.projectId, task = props.task.id
  const choices = { ...JSON.parse(JSON.stringify(selection.value)), files: filePaths.value.split('\n').map(x => x.trim()).filter(Boolean) }
  history.value = false; busy.value = true; error.value = ''; message.value = ''; snapshot.value = null
  try {
    const data = await projectWorkExecutionApi.previewContext(project, task, choices)
    if (seq !== generation) return
    snapshot.value = data; context.value = { selection: choices, expected_fingerprint: data.fingerprint }; emit('context', context.value)
  } catch (failure) { if (seq === generation) error.value = failure?.message || '读取资料失败，选择仍保留' }
  finally { if (seq === generation) busy.value = false }
}
async function openPreview() {
  open.value = true; history.value = false
  const seq = generation
  try { const data = await governanceBoardApi.listBlueprints(props.projectId); if (seq === generation) blueprints.value = data.documents || [] }
  catch (failure) { if (seq === generation) error.value = failure?.message || '蓝图列表不可用' }
  if (seq !== generation) return
  await preview()
}
async function showHistory(kind, id) {
  const seq = ++generation
  open.value = true; history.value = true; busy.value = true; error.value = ''; snapshot.value = null; message.value = ''
  try { const data = await projectWorkExecutionApi.getContext(props.projectId, props.task.id, kind, id); if (seq === generation) { snapshot.value = data.snapshot; message.value = data.message } }
  catch (failure) { if (seq === generation) error.value = failure?.message || '历史资料不可访问' }
  finally { if (seq === generation) busy.value = false }
}
defineExpose({ showHistory })
</script>
<style scoped>
label { display: grid; gap: 8px; margin: 16px 0; }
article { border-bottom: 1px solid var(--gray-200); padding: 12px 0; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
</style>
