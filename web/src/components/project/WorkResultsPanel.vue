<template>
  <section class="result-panel">
    <h2>交付与办理</h2>
    <a-alert v-if="task.legacy_completion" type="info" message="历史完成，未记录验收依据" show-icon />
    <a-alert v-else-if="task.status === 'done' && !task.acceptance_current" type="warning" message="历史结果按旧要求验收，尚无当前要求的验收依据" show-icon />
    <p class="muted">要求修订 {{ task.criteria_revision || 1 }} · 结果 {{ task.results?.length || 0 }} 份。执行成功、结果接受与工作完成分别记录。</p>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-alert v-if="missingResult" type="warning" show-icon message="指定结果不在当前工作中，未替换为其他结果。请核对入口或刷新。" />
    <div class="result-selector" aria-label="选择交付结果">
      <button v-for="item in task.results || []" :key="item.id" type="button" :aria-pressed="item.id === selectedId" @click="selectResult(item.id)">
        {{ statusName(item.status) }} · 要求 {{ item.criteria_revision || '未记录' }} · {{ item.id.slice(0, 8) }}
        <span>{{ formatDateTime(item.created_at) }} · {{ item.summary }}</span>
      </button>
    </div>
    <p v-if="!task.results?.length" class="muted">尚无业务结果记录，可直接人工交付，无需议题或智能体。</p>
    <article v-for="result in selectedResult ? [selectedResult] : []" :key="result.id" :id="`work-result-${result.id}`" class="result-card">
      <h3>结果 {{ result.id.slice(0, 8) }} · {{ statusName(result.status) }} · {{ formatDateTime(result.created_at) }}</h3>
      <p class="muted">{{ result.origin_kind === 'automatic' ? '执行自动导入' : '人工提交' }} · 提交者 {{ result.submitted_by }} · 要求修订 {{ result.criteria_revision || '未记录' }}</p>
      <p v-if="result.source_execution_id"><a :href="`#work-execution-${result.source_execution_id}`">查看当次执行来源</a></p>
      <p v-if="result.source_delegation_id">来源委派：{{ result.source_delegation_id }}</p>
      <h4>结果摘要</h4><pre>{{ result.summary }}</pre>
      <p v-if="result.unresolved">未解决事项：{{ result.unresolved }}</p>
      <a-alert v-if="result.criteria_changed" type="warning" show-icon message="该结果基于旧要求；核对原依据后可记录未接受，接受需补充当前要求的交付。" />
      <details open><summary>提交时验收条件{{ result.criteria_changed ? '（与当前要求不同）' : '' }}</summary><pre>{{ result.criteria_snapshot === null ? '旧执行未记录可核对条件，不能作为当前完成依据，请补充人工结果' : result.criteria_snapshot || '当时未填写条件' }}</pre></details>
      <p v-if="!(result.evidence || []).some(item => ['file', 'attachment'].includes(item.kind))" class="muted">未登记文件交付物；纯文字事项仍可验收。</p>
      <details v-if="result.criteria_changed"><summary>当前验收条件 · 修订 {{ task.criteria_revision || 1 }}</summary><pre>{{ task.acceptance_criteria || '当前未填写条件' }}</pre></details>
      <a-alert v-if="needsRecheck[result.id] && result.status === 'pending'" type="warning" show-icon message="发生版本冲突，请重新核对结果与要求。">
        <template #description><pre>{{ task.acceptance_criteria || '当前条件为空' }}</pre><a-button @click="needsRecheck[result.id] = false; error = ''">已核对最新结果与要求</a-button></template>
      </a-alert>
      <h4>交付文件与引用</h4><ul><li v-for="(item, index) in result.evidence" :key="index">
        <a v-if="item.kind === 'url'" :href="item.value" target="_blank" rel="noopener noreferrer">{{ item.title || item.value }}</a>
        <router-link v-else-if="item.kind === 'file' && item.workspace_path" :to="{ name: 'workspace', query: { open: item.workspace_path } }" target="_blank">查看文件：{{ item.title || item.value }}</router-link>
        <a-button v-else-if="item.kind === 'attachment'" type="link" :disabled="item.availability === 'unavailable'" @click="emit('download-attachment', item.value)">下载附件：{{ item.title || task.attachments?.find(file => file.id === item.value)?.file_name || item.value }}</a-button>
        <span v-else>{{ item.title || item.value }}</span> · {{ item.availability_message }}
      </li></ul>
      <p class="muted">文件独立打开用于对照；返回本页仍保留所选结果与意见。预览能力沿用个人空间，未支持格式可下载。</p>
      <p v-if="result.reviewed_at">{{ result.reviewed_by }} · {{ formatDateTime(result.reviewed_at) }} · {{ result.review_comment || '未填写意见' }}</p>
      <ResultFeedbackPanel :project-id="projectId" :task-id="task.id" :task-number="task.number" :result="result" @refresh="emit('refresh')" />
      <a-button v-if="result.status === 'accepted' && !result.criteria_changed && task.status !== 'done'" type="primary" :loading="completionBusy" :disabled="completionBusy" @click="emit('complete-task')">完成工作（已接受当前结果）</a-button>
      <a-alert v-if="result.status !== 'pending' && comments[result.id]" type="warning" show-icon message="该结果已办理。你的未提交意见保留用于对照，不会自动重放。">
        <template #description><pre>{{ comments[result.id] }}</pre><a-button @click="comments[result.id] = ''">放弃本地意见</a-button></template>
      </a-alert>
      <template v-if="result.status === 'pending'">
        <a-textarea v-model:value="comments[result.id]" aria-label="验收意见" :rows="2" :maxlength="100000" />
        <div class="result-actions">
          <a-button :loading="busy" :disabled="needsRecheck[result.id]" @click="review(result, 'not_accepted', false)">未接受</a-button>
          <a-button :loading="busy" :disabled="needsRecheck[result.id] || result.criteria_changed || result.criteria_snapshot === null" @click="review(result, 'accepted', false)">接受结果</a-button>
          <a-button :loading="busy" :disabled="needsRecheck[result.id] || result.criteria_changed || result.criteria_snapshot === null" @click="review(result, 'accepted', true)">接受并完成</a-button>
        </div>
      </template>
    </article>
    <details class="result-editor" :open="!task.results?.length"><summary>人工提交新结果</summary>
      <p class="muted">人工提交不创建执行记录；文件可访问不等于符合要求。提交并完成仍执行后端完成校验。</p>
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
    </details>
    <details class="result-editor"><summary>当前要求与编辑</summary>
    <h2>要求</h2>
    <label>工作描述<a-textarea v-model:value="description" aria-label="工作描述" :rows="3" :maxlength="100000" /></label>
    <label>验收条件（Markdown）<a-textarea v-model:value="criteria" aria-label="验收条件" :rows="5" :maxlength="100000" placeholder="明确预期结果、判断方式及可核对证据；简单事项可留空。" /></label>
    <p v-if="!task.acceptance_criteria" class="muted">尚未填写验收条件，派发前请核对要求；简单事项仍可人工提交并验收。</p>
    <a-button :loading="busy" @click="saveRequirements">保存要求</a-button>
    <a-button @click="emit('refresh')">刷新最新要求</a-button>
    <a-alert v-if="revision !== (task.criteria_revision || 1)" type="warning" show-icon message="要求已变更，当前输入仍保留。请核对下方最新条件，再决定是否使用本草稿。">
      <template #description><pre>{{ task.acceptance_criteria || '当前条件为空' }}</pre><a-button @click="adoptRequirements">加载最新要求，保留结果草稿</a-button></template>
    </a-alert>
    </details>

  </section>
</template>

<script setup>
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import ResultFeedbackPanel from './ResultFeedbackPanel.vue'
import { projectWorkApi } from '@/apis/project_work_api'
import { formatDateTime } from '@/utils/time'
import { useUserStore } from '@/stores/user'
import { getReviewDraft, setReviewDraft, clearReviewScope, reviewDrafts } from '@/utils/resultReviewDrafts'

const props = defineProps({ projectId: { type: String, required: true }, task: { type: Object, required: true }, executions: { type: Array, default: () => [] }, anchor: { type: String, default: '' }, completionBusy: { type: Boolean, default: false } })
const emit = defineEmits(['refresh', 'complete', 'select-result', 'download-attachment', 'complete-task'])
const user = useUserStore()
const selectedId = ref('')
const selectedResult = computed(() => (props.task.results || []).find(item => item.id === selectedId.value))
const missingResult = computed(() => Boolean(selectedId.value && !selectedResult.value))
function selectResult(id) { selectedId.value = id; emit('select-result', id) }
watch([() => props.task.id, () => props.anchor, () => props.task.results], () => {
  const anchored = props.anchor.startsWith('#work-result-') ? props.anchor.slice(13) : ''
  const results = props.task.results || []
  if (anchored) selectedId.value = anchored
  else if (!results.some(item => item.id === selectedId.value)) selectedId.value = results.find(item => item.status === 'pending' && !item.criteria_changed)?.id || results[0]?.id || ''
}, { immediate: true })
const description = ref(''), criteria = ref(''), revision = ref(1)
const summary = ref(''), unresolved = ref(''), source = ref(), evidence = ref([]), comments = ref({})
const error = ref(''), busy = ref(false), needsRecheck = ref({})
let requestId = '', requestComplete = null, identity = '', generation = 0
onBeforeUnmount(() => { generation += 1 })
const statusName = (value) => ({ pending: '待验收', accepted: '已接受', not_accepted: '未接受' })[value] || value
watch([() => props.projectId, () => props.task.id, () => user.uid], () => {
  generation += 1
  identity = `${props.projectId}/${props.task.id}`
  description.value = props.task.description || ''
  criteria.value = props.task.acceptance_criteria || ''
  revision.value = props.task.criteria_revision || 1
  summary.value = ''; unresolved.value = ''; source.value = undefined; evidence.value = []; comments.value = {}; error.value = ''; busy.value = false; requestId = ''; needsRecheck.value = {}
}, { immediate: true, flush: 'sync' })

watch([() => props.projectId, () => props.task.id, () => props.task.results, () => user.uid, reviewDrafts], (current, previous) => {
  if (previous && (current[3] !== previous[3] || current[4] !== previous[4])) comments.value = {}
  const restored = {}
  for (const result of props.task.results || []) {
    restored[result.id] = comments.value[result.id] ?? getReviewDraft(user.uid, props.projectId, props.task.id, result.id)
  }
  comments.value = restored
}, { immediate: true })
watch(comments, () => {
  for (const [id, comment] of Object.entries(comments.value)) setReviewDraft(user.uid, props.projectId, props.task.id, id, comment)
}, { deep: true, flush: 'sync' })

watch([summary, unresolved, source, evidence, revision], () => { requestId = '' }, { deep: true, flush: 'sync' })

async function act(action, onSuccess, reviewId) {
  const version = generation
  busy.value = true; error.value = ''
  try {
    const result = await action()
    if (version !== generation) return
    onSuccess?.(result)
    emit('refresh')
  } catch (failure) {
    if (version === generation) {
      error.value = failure?.message || '保存失败，输入仍保留'
      if ([401, 403, 404].includes(failure?.status)) { clearReviewScope(user.uid, props.projectId, props.task.id); comments.value = {}; emit('refresh') }
      if (failure?.status === 409) {
        if (reviewId) needsRecheck.value[reviewId] = true
        error.value = `${failure?.message || '版本冲突'}；意见已保留。请核对刷新后的结果、当前条件与提交时条件，再确认继续。`
        emit('refresh')
      }
    }
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
    return act(() => projectWorkApi.reviewResult(project, task, result.id, { ...payload, git_outcomes_confirmed: confirmed }), () => { setReviewDraft(user.uid, project, task, result.id, ''); delete comments.value[result.id] }, result.id)
  }
  return complete ? emit('complete', send) : send()
}
</script>

<style scoped>
.result-selector { max-height: 160px; overflow-y: auto; display: flex; flex-wrap: wrap; gap: 8px; }
.result-selector button { max-width: 280px; text-align: left; padding: 10px; border: 1px solid var(--gray-200); background: var(--gray-0); color: var(--gray-800); border-radius: 8px; cursor: pointer; }
.result-selector button[aria-pressed="true"] { border-color: var(--main-color); background: var(--main-10); }
.result-selector span { display: block; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-size: 12px; }
.result-editor { padding: 16px; border: 1px solid var(--gray-200); border-radius: 8px; }
.result-editor[open] > summary { margin-bottom: 16px; }
.result-editor label { margin: 12px 0; }
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
