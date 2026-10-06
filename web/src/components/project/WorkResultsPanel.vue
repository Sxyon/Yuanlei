<template>
  <section class="result-panel">
    <h2>要求</h2>
    <label>工作描述<a-textarea v-model:value="description" aria-label="工作描述" :rows="3" :maxlength="100000" /></label>
    <label>验收条件（Markdown）<a-textarea v-model:value="criteria" aria-label="验收条件" :rows="5" :maxlength="100000" placeholder="明确预期结果、判断方式及可核对证据；简单事项可留空。" /></label>
    <p v-if="!task.acceptance_criteria" class="muted">尚未填写验收条件，派发前请核对要求；简单事项仍可人工提交并验收。</p>
    <a-button :loading="busy" @click="saveRequirements">保存要求</a-button>
    <a-button @click="emit('refresh')">刷新最新要求</a-button>
    <a-alert v-if="revision !== (task.criteria_revision || 1)" type="warning" show-icon message="要求已变更，当前输入仍保留。请核对下方最新条件，再决定是否使用本草稿。">
      <template #description><pre>{{ task.acceptance_criteria || '当前条件为空' }}</pre><a-button @click="adoptRequirements">加载最新要求，保留结果草稿</a-button></template>
    </a-alert>
    <h2>结果</h2>
    <a-alert v-if="task.legacy_completion" type="info" message="历史完成，未记录验收依据" show-icon />
    <a-alert v-else-if="task.status === 'done' && !task.acceptance_current" type="warning" message="工作保留已完成状态；历史结果按旧要求验收，尚无当前要求的验收依据" show-icon />
    <p class="muted">业务结果与普通评论分开记录；人工提交不会生成执行记录。证据可访问不等于符合要求，接受由你明确判断。</p>
    <label>结果摘要<a-textarea v-model:value="summary" aria-label="结果摘要" :rows="4" :maxlength="100000" /></label>
    <label>未解决事项<a-textarea v-model:value="unresolved" aria-label="未解决事项" :rows="2" :maxlength="100000" /></label>
    <label>执行来源（可选）<a-select v-model:value="source" aria-label="结果执行来源" allow-clear placeholder="人工提交，无执行来源">
      <a-select-option v-for="attempt in executions" :key="attempt.id" :value="attempt.id">{{ attempt.agent_slug }} · {{ attempt.status }} · {{ formatDateTime(attempt.created_at) }}</a-select-option>
    </a-select></label>
    <h3>证据引用</h3>
    <div v-for="(item, index) in evidence" :key="index" class="evidence-input">
      <a-select v-model:value="item.kind" aria-label="证据类型"><a-select-option value="file">项目文件</a-select-option><a-select-option value="attachment">工作附件</a-select-option><a-select-option value="url">网页引用</a-select-option></a-select>
      <a-select v-if="item.kind === 'attachment'" v-model:value="item.value" aria-label="证据附件"><a-select-option v-for="file in task.attachments || []" :key="file.id" :value="file.id">{{ file.file_name }}</a-select-option></a-select>
      <a-input v-else v-model:value="item.value" :aria-label="item.kind === 'url' ? '证据网页地址' : '证据文件路径'" :placeholder="item.kind === 'url' ? 'https://example.com/result' : '项目目录内路径，例如 /outputs/result.md'" :maxlength="2048" />
      <a-button @click="evidence.splice(index, 1)">移除</a-button>
    </div>
    <p class="muted">网页仅为引用，系统未读取或验证。文件与附件在提交、验收和完成时检查可访问性。</p>
    <a-button :disabled="evidence.length >= 20" @click="evidence.push({ kind: 'file', value: '', title: '' })">添加证据</a-button>
    <div class="result-actions">
      <a-button :loading="busy" :disabled="!summary.trim()" @click="submit(false)">提交待验收</a-button>
      <a-button type="primary" :loading="busy" :disabled="!summary.trim()" @click="submit(true)">提交并完成</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <p v-if="!task.results?.length" class="muted">尚无业务结果记录。</p>
    <article v-for="result in task.results || []" :key="result.id" :id="`work-result-${result.id}`" class="result-card">
      <h3>{{ statusName(result.status) }} · {{ formatDateTime(result.created_at) }}</h3>
      <p class="muted">{{ result.origin_kind === 'automatic' ? '执行自动导入' : '人工提交' }} · 提交者 {{ result.submitted_by }} · 要求修订 {{ result.criteria_revision || '未记录' }}</p>
      <p v-if="result.source_execution_id"><a :href="`#work-execution-${result.source_execution_id}`">查看当次执行来源</a></p>
      <p v-if="result.source_delegation_id">来源委派：{{ result.source_delegation_id }}</p>
      <pre>{{ result.summary }}</pre>
      <p v-if="result.unresolved">未解决事项：{{ result.unresolved }}</p>
      <details><summary>提交时验收条件{{ result.criteria_changed ? '（与当前要求不同）' : '' }}</summary><pre>{{ result.criteria_snapshot === null ? '旧执行未记录可核对条件，不能作为当前完成依据，请补充人工结果' : result.criteria_snapshot || '当时未填写条件' }}</pre></details>
      <ul><li v-for="(item, index) in result.evidence" :key="index">
        <a v-if="item.kind === 'url'" :href="item.value" target="_blank" rel="noopener noreferrer">{{ item.title || item.value }}</a>
        <span v-else>{{ item.title || item.value }}</span> · {{ item.availability_message }}
      </li></ul>
      <p v-if="result.reviewed_at">{{ result.reviewed_by }} · {{ formatDateTime(result.reviewed_at) }} · {{ result.review_comment || '未填写意见' }}</p>
      <ResultFeedbackPanel :project-id="projectId" :task-id="task.id" :task-number="task.number" :result="result" @refresh="emit('refresh')" />
      <template v-if="result.status === 'pending'">
        <a-textarea v-model:value="comments[result.id]" aria-label="验收意见" :rows="2" :maxlength="100000" />
        <div class="result-actions">
          <a-button :loading="busy" @click="review(result, 'not_accepted', false)">未接受</a-button>
          <a-button :loading="busy" @click="review(result, 'accepted', false)">接受结果</a-button>
          <a-button :loading="busy" @click="review(result, 'accepted', true)">接受并完成</a-button>
        </div>
      </template>
    </article>
  </section>
</template>

<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import ResultFeedbackPanel from './ResultFeedbackPanel.vue'
import { projectWorkApi } from '@/apis/project_work_api'
import { formatDateTime } from '@/utils/time'

const props = defineProps({ projectId: { type: String, required: true }, task: { type: Object, required: true }, executions: { type: Array, default: () => [] } })
const emit = defineEmits(['refresh', 'complete'])
const description = ref(''), criteria = ref(''), revision = ref(1)
const summary = ref(''), unresolved = ref(''), source = ref(), evidence = ref([]), comments = ref({})
const error = ref(''), busy = ref(false)
let requestId = '', requestComplete = null, identity = '', generation = 0
onBeforeUnmount(() => { generation += 1 })
const statusName = (value) => ({ pending: '待验收', accepted: '已接受', not_accepted: '未接受' })[value] || value
watch([() => props.projectId, () => props.task.id], () => {
  generation += 1
  identity = `${props.projectId}/${props.task.id}`
  description.value = props.task.description || ''
  criteria.value = props.task.acceptance_criteria || ''
  revision.value = props.task.criteria_revision || 1
  summary.value = ''; unresolved.value = ''; source.value = undefined; evidence.value = []; comments.value = {}; error.value = ''; busy.value = false; requestId = ''
}, { immediate: true })
watch([summary, unresolved, source, evidence, revision], () => { requestId = '' }, { deep: true, flush: 'sync' })

async function act(action, onSuccess) {
  const version = generation
  busy.value = true; error.value = ''
  try {
    const result = await action()
    if (version !== generation) return
    onSuccess?.(result)
    emit('refresh')
  } catch (failure) {
    if (version === generation) error.value = failure?.message || '保存失败，输入仍保留'
  } finally { if (version === generation) busy.value = false }
}
function adoptRequirements() {
  description.value = props.task.description || ''
  criteria.value = props.task.acceptance_criteria || ''
  revision.value = props.task.criteria_revision || 1
  error.value = ''
}
function saveRequirements() {
  const payload = { description: description.value || null, acceptance_criteria: criteria.value, expected_revision: revision.value }
  return act(() => projectWorkApi.updateRequirements(props.projectId, props.task.id, payload), (saved) => { revision.value = saved.criteria_revision })
}
function submit(complete) {
  if (!requestId || requestComplete !== complete) requestId = crypto.randomUUID()
  requestComplete = complete
  const project = props.projectId, task = props.task.id, context = identity, version = generation
  const payload = { request_id: requestId, summary: summary.value, unresolved: unresolved.value, evidence: evidence.value.map(item => ({ ...item })), source_execution_id: source.value || null, expected_revision: revision.value, complete }
  const send = (confirmed = false) => {
    if (context !== identity || version !== generation) return
    return act(() => projectWorkApi.submitResult(project, task, { ...payload, git_outcomes_confirmed: confirmed }), () => { if (summary.value !== payload.summary || unresolved.value !== payload.unresolved || JSON.stringify(evidence.value) !== JSON.stringify(payload.evidence) || (source.value || null) !== payload.source_execution_id) return; summary.value = ''; unresolved.value = ''; evidence.value = []; source.value = undefined; requestId = '' })
  }
  return complete ? emit('complete', send) : send()
}
function review(result, status, complete) {
  const project = props.projectId, task = props.task.id, context = identity, version = generation
  const payload = { status, complete, comment: comments.value[result.id] || '', expected_version: result.version, expected_revision: props.task.criteria_revision || 1 }
  const send = (confirmed = false) => {
    if (context !== identity || version !== generation) return
    return act(() => projectWorkApi.reviewResult(project, task, result.id, { ...payload, git_outcomes_confirmed: confirmed }))
  }
  return complete ? emit('complete', send) : send()
}
</script>

<style scoped>
.result-panel { display: grid; gap: 16px; }
.result-panel label { display: grid; gap: 8px; }
.result-panel pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.result-panel .muted { color: var(--gray-600); }
.result-actions, .evidence-input { display: flex; flex-wrap: wrap; gap: 8px; }
.evidence-input > :nth-child(2) { flex: 1; min-width: 180px; }
.evidence-input > :first-child { width: 140px; }
.result-card a { color: var(--color-primary-500); overflow-wrap: anywhere; }
.result-card { padding: 16px; border: 1px solid var(--gray-200); border-radius: 8px; }
</style>
