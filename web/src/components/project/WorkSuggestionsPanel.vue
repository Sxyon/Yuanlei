<template>
  <div class="suggestions-panel">
    <p v-if="!suggestions.length">暂无工作建议，可在上方记录待处理事项。</p>
    <ul>
      <li v-for="item in suggestions" :id="`task-${item.id}`" :key="item.id">
        <strong>{{ item.title }}</strong>
        <a-tag>{{
          item.work
            ? '已纳入'
            : { proposed: '待处理', canonical: '待补充关联', rejected: '已拒绝' }[item.status]
        }}</a-tag>
        <p v-if="item.description">{{ item.description }}</p>
        <p>
          来源：{{ sourceChannelLabel(item.source?.channel || 'project') }}
          <a
            v-if="item.source?.url"
            :href="item.source.url"
            target="_blank"
            rel="noopener noreferrer"
            >原文</a
          >
        </p>
        <p v-if="item.topic_id">
          议题：{{ topics.find((t) => t.id === item.topic_id)?.title || '历史议题' }}
        </p>
        <p v-if="item.decision_id">
          决策：{{ decisions.find((d) => d.id === item.decision_id)?.title || '历史决策' }}
        </p>
        <p v-if="item.review?.note">处理说明：{{ item.review.note }}</p>
        <RouterLink v-if="item.work" :to="workLink(item.work.id)"
          >{{ item.work.number }} · {{ item.work.title }}</RouterLink
        >
        <a-button v-else-if="item.status !== 'rejected'" size="small" @click="open(item)"
          >纳入为工作</a-button
        >
        <a-button v-if="item.status === 'proposed'" size="small" @click="$emit('reject', item)"
          >拒绝</a-button
        >
      </li>
    </ul>
    <a-modal
      :open="!!selected"
      title="纳入为工作"
      :footer="null"
      :mask-closable="false"
      @cancel="close"
    >
      <form v-if="selected" @submit.prevent="submit">
        <a-radio-group v-model:value="mode" :disabled="busy"
          ><a-radio-button value="create">新建工作</a-radio-button
          ><a-radio-button value="link">关联已有工作</a-radio-button></a-radio-group
        >
        <p v-if="loading">正在读取当前项目的工作与编号…</p>
        <template v-else-if="mode === 'create'">
          <label>工作标题<a-input v-model:value="title" :disabled="busy" /></label>
          <label
            >工作描述<a-textarea v-model:value="description" :disabled="busy" :rows="4"
          /></label>
          <WorkSourceFields
            v-model:topic-id="topicId"
            v-model:decision-id="decisionId"
            v-model:review-confirmed="reviewConfirmed"
            :topics="workTopics"
            :decisions="decisions"
            :disabled="busy"
          />
          <div v-if="!projectCode">
            <label
              >项目编号缩写<a-input
                v-model:value="codeDraft"
                placeholder="如 PROJ"
                :disabled="busy"
            /></label>
            <a-button :loading="busy" @click="saveCode">保存项目缩写</a-button>
          </div>
          <div v-if="topicId && !workTopics.find((t) => t.id === topicId)?.code">
            <label
              >所选议题编号缩写<a-input
                v-model:value="topicCodeDraft"
                placeholder="如 PLAN"
                :disabled="busy"
            /></label>
            <a-button :loading="busy" @click="saveTopicCode">保存议题缩写</a-button>
          </div>
        </template>
        <label v-else
          >当前项目正式工作
          <a-select v-model:value="workId" :disabled="busy" placeholder="选择已有工作"
            ><a-select-option v-for="work in works" :key="work.id" :value="work.id"
              >{{ work.number }} · {{ work.title }}</a-select-option
            ></a-select
          >
        </label>
        <p v-if="mode === 'link'">只建立建议关联，保留已有工作的标题、状态、负责人和主要来源。</p>
        <label>纳入说明（可选）<a-textarea v-model:value="reason" :disabled="busy" /></label>
        <a-alert v-if="error" type="error" show-icon :message="error" />
        <RouterLink v-if="existingWork" :to="workLink(existingWork.id)"
          >打开已纳入的正式工作</RouterLink
        >
        <div>
          <a-button :disabled="busy" @click="close">取消</a-button
          ><a-button
            type="primary"
            html-type="submit"
            :loading="busy"
            :disabled="loading || (mode === 'create' ? !title.trim() : !workId)"
            >确认纳入</a-button
          >
        </div>
      </form>
    </a-modal>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { useUserStore } from '@/stores/user'
import { getGovernanceDraft, setGovernanceDraft, clearGovernanceDrafts } from '@/utils/governanceDrafts'
import { RouterLink, useRouter } from 'vue-router'
import { governanceBoardApi } from '@/apis/governance_board_api'
import { projectWorkApi } from '@/apis/project_work_api'
import WorkSourceFields from './WorkSourceFields.vue'
import { sourceChannelLabel } from '@/utils/governanceBoard'
const props = defineProps({
  projectId: String,
  suggestions: { type: Array, default: () => [] },
  topics: { type: Array, default: () => [] },
  decisions: { type: Array, default: () => [] }
})
const emit = defineEmits(['reject', 'admitted', 'visibility-lost'])
const router = useRouter()
const user = useUserStore()
const selected = ref(null),
  mode = ref('create'),
  title = ref(''),
  description = ref(''),
  topicId = ref(),
  decisionId = ref(),
  reviewConfirmed = ref(false),
  workId = ref(),
  reason = ref('')
const works = ref([]),
  workTopics = ref([]),
  projectCode = ref(''),
  codeDraft = ref(''),
  topicCodeDraft = ref(''),
  error = ref(''),
  existingWork = ref(null),
  loading = ref(false),
  busy = ref(false)
let generation = 0
let restoring = false
const fields = { mode, title, description, topicId, decisionId, workId, reason, codeDraft, topicCodeDraft }
watch(Object.values(fields), () => {
  if (!restoring && selected.value && user.uid) setGovernanceDraft(user.uid, props.projectId, `suggestion:${selected.value.id}`, Object.fromEntries(Object.entries(fields).map(([name, value]) => [name, value.value])))
}, { deep: true, flush: 'sync' })
const workLink = (id) => ({
  name: 'ProjectWorkTaskView',
  params: { project_id: props.projectId, task_id: id }
})
function close() {
  if (busy.value) return
  generation++
  selected.value = null
  error.value = ''
  loading.value = false
}
async function open(item) {
  const seq = ++generation
  restoring = true
  selected.value = item
  mode.value = 'create'
  title.value = item.title
  description.value = item.description || ''
  topicId.value = item.topic_id || undefined
  decisionId.value = item.decision_id || undefined
  reviewConfirmed.value = false
  workId.value = undefined
  reason.value = ''
  error.value = ''
  existingWork.value = null
  codeDraft.value = ''
  topicCodeDraft.value = ''
  const saved = getGovernanceDraft(user.uid, props.projectId, `suggestion:${item.id}`)
  if (saved) for (const [name, value] of Object.entries(fields)) value.value = saved[name]
  reviewConfirmed.value = false
  restoring = false
  loading.value = true
  try {
    const [tasks, topics, code] = await Promise.all([
      projectWorkApi.listTasks(props.projectId),
      projectWorkApi.listTopics(props.projectId),
      projectWorkApi.getCode(props.projectId)
    ])
    if (seq !== generation) return
    works.value = tasks
    workTopics.value = topics
    projectCode.value = code?.code || ''
  } catch (e) {
    if (seq === generation) {
      error.value = e?.message || '读取失败，请关闭后重试'
      if ((e?.status || e?.response?.status) === 404) emit('visibility-lost', e)
      if ([401, 403].includes(e?.status || e?.response?.status)) { clearGovernanceDrafts(user.uid, props.projectId); selected.value = null; emit('visibility-lost', e) }
    }
  } finally {
    if (seq === generation) loading.value = false
  }
}
async function saveCode() {
  const seq = generation,
    project = props.projectId
  busy.value = true
  error.value = ''
  try {
    const code = await projectWorkApi.configureCode(project, codeDraft.value)
    if (seq === generation) projectCode.value = code.code
  } catch (e) {
    if (seq === generation) { if ((e?.status || e?.response?.status) === 404) emit('visibility-lost', e); error.value = e?.message || '编号保存失败，输入已保留'; if ([401, 403].includes(e?.status || e?.response?.status)) { clearGovernanceDrafts(user.uid, project); selected.value = null; emit('visibility-lost', e) } }
  } finally {
    if (seq === generation) busy.value = false
  }
}
async function saveTopicCode() {
  const seq = generation,
    project = props.projectId,
    topic = topicId.value
  busy.value = true
  error.value = ''
  try {
    await projectWorkApi.configureTopicCode(project, topic, topicCodeDraft.value)
    const topics = await projectWorkApi.listTopics(project)
    if (seq === generation) workTopics.value = topics
  } catch (e) {
    if (seq === generation) { if ((e?.status || e?.response?.status) === 404) emit('visibility-lost', e); error.value = e?.message || '议题编号保存失败，输入已保留'; if ([401, 403].includes(e?.status || e?.response?.status)) { clearGovernanceDrafts(user.uid, project); selected.value = null; emit('visibility-lost', e) } }
  } finally {
    if (seq === generation) busy.value = false
  }
}
async function submit() {
  if (busy.value || loading.value) return
  const project = props.projectId,
    item = selected.value,
    seq = generation
  busy.value = true
  error.value = ''
  try {
    const payload =
      mode.value === 'link'
        ? { mode: 'link', work_task_id: workId.value, review_note: reason.value }
        : {
            mode: 'create',
            title: title.value,
            description: description.value,
            topic_id: topicId.value || null,
            source_decision_id: decisionId.value || null,
            review_confirmed: reviewConfirmed.value,
            review_note: reason.value
          }
    const result = await governanceBoardApi.admitTask(project, item.id, payload)
    if (seq !== generation) return
    setGovernanceDraft(user.uid, project, `suggestion:${item.id}`, null)
    selected.value = null
    emit('admitted')
    await router.push(workLink(result.work.id))
  } catch (e) {
    if (seq === generation) {
      error.value = e?.message || '纳入失败，输入已保留'
      if ((e?.status || e?.response?.status) === 404) emit('visibility-lost', e)
      if ([401, 403].includes(e?.status || e?.response?.status)) {
        clearGovernanceDrafts(user.uid, project); selected.value = null; emit('visibility-lost', e); return
      }
      if (e?.response?.data?.detail?.code === 'suggestion_already_admitted') {
        try {
          const board = await governanceBoardApi.getProjectBoard(project)
          if (seq === generation)
            existingWork.value =
              board.governance?.tasks?.find((s) => s.id === item.id)?.work || null
        } catch {
          /* 保留原错误及草稿，列表刷新仍可读取原工作。 */
        }
      }
    }
  } finally {
    if (seq === generation) busy.value = false
  }
}
watch(() => props.decisions, () => { reviewConfirmed.value = false }, { deep: true })
watch(
  () => [props.projectId, user.uid],
  () => {
    generation++
    selected.value = null
    busy.value = false
    loading.value = false
    error.value = ''
  }
)
</script>
<style scoped>
.suggestions-panel ul {
  list-style: none;
  padding: 0;
}
.suggestions-panel li {
  padding: 12px 0;
  border-bottom: 1px solid var(--border-color);
  overflow-wrap: anywhere;
}
.suggestions-panel a {
  color: var(--main-color);
}
form,
label {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
</style>
