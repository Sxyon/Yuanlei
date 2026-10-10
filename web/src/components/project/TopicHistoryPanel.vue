<template>
  <section class="topic-history">
    <a-alert
      v-if="topic.execution_hint"
      show-icon
      :type="topic.execution_hint === 'pause_recommended' ? 'warning' : 'info'"
      :message="topic.execution_hint === 'pause_recommended' ? '建议暂停原方案' : '原方案继续执行'"
      description="此提示仅记录议题意见，不暂停关联任务或执行记录，也不撤销正式决策。"
    />
    <p>纳入议题不等于批准决策。正文修改保留修订，不覆盖正式决策。</p>
    <RouterLink
      class="source-work-link"
      v-if="!topic.archived_at"
      :to="{
        name: 'ProjectWorkTasksView',
        params: { project_id: projectId },
        query: { create: '1', topic_id: topic.id }
      }"
      >从此议题创建工作</RouterLink
    >
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <details v-if="!topic.archived_at" :open="!!action" class="topic-maintenance">
      <summary>议题维护（关闭、重开、归档等）</summary>
      <a-select v-model:value="action" aria-label="议题操作" style="min-width: 160px">
        <a-select-option v-if="topic.admission_status === 'rejected'" value="resubmit"
          >重新提交纳入</a-select-option
        >
        <a-select-option
          v-if="topic.admission_status === 'canonical' && topic.progress === 'open'"
          value="decide"
          >标记已形成决策</a-select-option
        >
        <a-select-option v-if="topic.progress !== 'closed'" value="close">关闭议题</a-select-option>
        <a-select-option v-if="topic.progress !== 'open'" value="reopen">重开议题</a-select-option>
        <a-select-option value="archive">归档</a-select-option>
        <a-select-option value="delete">删除</a-select-option>
      </a-select>
      <a-select
        v-if="action === 'decide'"
        v-model:value="decisionId"
        aria-label="已批准关联决策"
        style="min-width: 200px"
      >
        <a-select-option
          v-for="decision in eligibleDecisions"
          :key="decision.id"
          :value="decision.id"
          >{{ decision.title }}</a-select-option
        >
      </a-select>
      <p v-if="action === 'decide'">
        确认后将清除本议题的继续执行或建议暂停提示；任务和执行记录保持各自状态。
      </p>
      <a-select
        v-if="action === 'reopen'"
        v-model:value="executionHint"
        aria-label="原方案执行提示"
        style="min-width: 180px"
      >
        <a-select-option value="continue">原方案继续执行</a-select-option>
        <a-select-option value="pause_recommended">建议暂停原方案</a-select-option>
      </a-select>
      <a-input
        v-model:value="reason"
        placeholder="操作原因（重开、关闭、重新提交、删除必填）"
        aria-label="议题操作原因"
        :maxlength="100000"
      />
      <p v-if="action === 'delete'">
        删除后，议题将从页面移除。已关联决策或任务的议题无法删除，请使用归档。
      </p>
      <a-button :danger="action === 'delete'" :disabled="busy || !action" @click="operate">{{
        actionLabel
      }}</a-button>
    </details>
    <a-button v-else :disabled="busy" @click="restore">恢复归档议题</a-button>
    <div v-if="!topic.archived_at" class="topic-discussion">
      <h4>持续研讨</h4>
      <a-select v-model:value="discussionType" aria-label="讨论类型" style="min-width: 140px">
        <a-select-option value="discussion">研讨</a-select-option>
        <a-select-option value="reconsideration">重议</a-select-option>
        <a-select-option value="correction">纠偏</a-select-option>
      </a-select>
      <a-textarea
        v-model:value="content"
        :maxlength="100000"
        :auto-size="{ minRows: 5, maxRows: 20 }"
        placeholder="写下讨论内容，支持 Markdown"
      />
      <a-button :disabled="busy || !content.trim()" @click="post">发布讨论</a-button>
      <span>讨论类型表达意图，发帖不会自动重开议题。</span>
    </div>
    <a-alert v-if="followupError" type="error" show-icon :message="followupError" />
    <a-button v-if="followupError" @click="loadFollowup">重新加载引用与确认</a-button>
    <TopicOutcomePanel
      v-if="followupReady"
      :project-id="projectId"
      :topic="topic"
      :candidates="candidates"
      :confirmations="confirmations"
      :draft="draft"
      @updated="refreshFollowup"
      @visibility-lost="failure => emit('visibility-lost', failure)"
    />
    <article v-if="focusedRevision" class="history-event">
      <h4>定位历史修订 {{ focusedRevision.number }}</h4>
      <h5>{{ focusedRevision.title }}</h5>
      <MarkdownPreview :content="focusedRevision.summary || '暂无正文'" /><MarkdownPreview
        :content="`${focusedRevision.expected_outcome || '未填写预期结果'}\n\n${focusedRevision.verification_conditions || '未填写核对条件'}`"
      />
    </article>
    <article v-if="focusedDiscussion" class="history-event">
      <h4>定位原讨论</h4>
      <TopicDiscussionCard
        :project-id="projectId"
        :topic-id="topic.id"
        :comment="focusedDiscussion"
        :candidates="candidates"
        :archived="!!topic.archived_at"
        :draft="draft"
        @updated="refreshFollowup"
      @visibility-lost="failure => emit('visibility-lost', failure)"
      />
    </article>
    <details :open="!!route?.query.comment_id || !!route?.query.revision">
    <summary>历史时间线 · 最新在前（{{ events.length }} 个已加载节点）</summary>
    <a-spin v-if="loading" />
    <p v-if="!loading && !events.length">暂无历史节点。</p>
    <article v-for="event in events" :key="event.sequence" class="history-event">
      <header>
        <strong>{{ eventLabel(event) }}</strong
        ><span
          >{{ event.author_name || event.created_by || '历史记录' }} ·
          {{ timestampLabel(event.created_at) }}</span
        >
      </header>
      <p v-if="event.reason">{{ event.reason }}</p>
      <p v-if="event.details?.result_id">
        <router-link
          :to="`/projects/${projectId}/work/tasks/${event.details.work_task_id}#work-result-${event.details.result_id}`"
          >查看来源工作结果</router-link
        >
      </p>
      <p v-if="event.details?.execution_hint">
        {{
          event.details.execution_hint === 'pause_recommended'
            ? '建议暂停原方案（不控制任务或执行记录）'
            : '原方案继续执行'
        }}
      </p>
      <p v-if="event.details?.decision_id">
        决策记录：{{
          decisions.find((d) => d.id === event.details.decision_id)?.title ||
          event.details.decision_id
        }}
        <router-link :to="{ query: { ...$route.query, decision_id: event.details.decision_id } }"
          >查看决策详情</router-link
        >
      </p>
      <router-link
        v-if="event.kind === 'reply' || event.kind === 'disposition'"
        :to="{
          query: {
            ...$route.query,
            comment_id: event.details.parent_comment_id || event.details.comment_id
          }
        }"
        >打开原讨论及回复 / 处理历史</router-link
      >
      <p v-if="event.kind === 'disposition'">
        {{ dispositionLabels[event.details.disposition] }} · 版本 {{ event.details.version }} ·
        {{ event.details.explanation }}
      </p>
      <router-link v-if="event.details?.reference?.href" :to="event.details.reference.href"
        >查看实际去向</router-link
      >
      <p v-if="event.kind === 'actual_confirmation'">
        {{ event.details.explanation }}
        <a @click="openConfirmation(event.details.confirmation_id)">查看确认及当时条件</a>
      </p>
      <TopicDiscussionCard
        v-if="event.comment && event.comment.id !== focusedDiscussion?.id"
        :project-id="projectId"
        :topic-id="topic.id"
        :comment="event.comment"
        :candidates="candidates"
        :archived="!!topic.archived_at"
        :draft="draft"
        @updated="refreshFollowup"
      @visibility-lost="failure => emit('visibility-lost', failure)"
      />
      <small v-if="event.comment && !event.revision_number">当时正文版本未知</small>
      <details v-if="event.revision">
        <summary>
          查看当时正文 · 修订 {{ event.revision.number
          }}{{ event.revision.origin === 'migration' ? '（迁移基线）' : '' }}
        </summary>
        <h5>{{ event.revision.title }}</h5>
        <MarkdownPreview :content="event.revision.summary || '暂无正文'" />
        <MarkdownPreview
          :content="`${event.revision.expected_outcome || '未填写预期结果'}\n\n${event.revision.verification_conditions || '未填写核对条件'}`"
        />
      </details>
    </article>
    <a-button v-if="nextBefore" :disabled="loading" @click="loadMore(false)">加载更早记录</a-button>
    </details>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, toRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { consumeIntent, stableIntent } from '@/utils/topicFollowup'
import TopicDiscussionCard from './TopicDiscussionCard.vue'
import TopicOutcomePanel from './TopicOutcomePanel.vue'
import { Modal } from 'ant-design-vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { describeBoardError } from '@/utils/governanceBoard'

const props = defineProps({
  projectId: { type: String, required: true },
  topic: { type: Object, required: true },
  decisions: { type: Array, default: () => [] },
  draft: { type: Object, default: () => ({ content: '', discussionType: 'discussion' }) }
})
const emit = defineEmits(['updated', 'visibility-lost'])
const route = useRoute()
const candidates = ref([]),
  confirmations = ref([]),
  focusedDiscussion = ref(null),
  focusedRevision = ref(null)
const followupError = ref(''),
  followupReady = ref(false)
const dispositionLabels = { adopted: '采纳', partial: '部分采纳', rejected: '不采纳' }
let followupGeneration = 0
const events = ref([])
const nextBefore = ref(null)
const loading = ref(false)
const busy = ref(false)
const error = ref('')
const sharedDraft = reactive(props.draft)
const action = toRef(sharedDraft, 'action')
const reason = toRef(sharedDraft, 'reason', '')
const decisionId = toRef(sharedDraft, 'decisionId')
const executionHint = toRef(sharedDraft, 'executionHint')
const discussionType = toRef(sharedDraft, 'discussionType', 'discussion')
const content = toRef(sharedDraft, 'content')
const actionLabel = computed(
  () =>
    ({
      resubmit: '重新提交纳入',
      decide: '确认已形成决策',
      close: '关闭议题',
      reopen: '重开议题',
      archive: '归档',
      delete: '删除'
    })[action.value] || '选择操作'
)
let generation = 0
let active = true
let deleteConfirmation
let cancelDeleteConfirmation
onBeforeUnmount(() => {
  active = false
  generation += 1
  followupGeneration += 1
  cancelDeleteConfirmation?.()
  deleteConfirmation?.destroy()
})
const timestampLabel = (raw) => (raw ? new Date(raw).toLocaleString('zh-CN') : '')
const eligibleDecisions = computed(() =>
  props.decisions.filter((d) => d.topic_id === props.topic.id && d.status === 'approved')
)
const labels = {
  decision_created: '新增决策草案',
  decision_revised: '修订决策草案',
  decision_approved: '批准决策',
  decision_supplemented: '批准补充决策',
  decision_superseded: '决策整条被替代',
  decision_revoked: '撤销决策',
  decision_deleted: '删除决策草案',
  decision_erratum: '追加文字勘误',
  decision_moved: '调整决策来源议题',
  created: '创建议题',
  revised: '修改正文',
  admitted: '纳入通过',
  rejected: '拒绝纳入',
  resubmit: '重新提交纳入',
  decide: '确认已形成决策',
  close: '关闭议题',
  reopen: '重开议题',
  archive: '归档',
  restore: '恢复归档',
  migration_baseline: '迁移基线',
  reply: '追加回复',
  disposition: '记录采纳处置',
  actual_confirmation: '记录实际确认 / 更正'
}
const discussionLabels = { discussion: '研讨', reconsideration: '重议', correction: '纠偏' }
function eventLabel(event) {
  return event.kind === 'comment'
    ? discussionLabels[event.comment?.discussion_type || 'discussion']
    : labels[event.kind] || event.kind
}
async function loadFollowup() {
  const seq = ++followupGeneration
  const topicId = props.topic.id
  followupError.value = ''
  try {
    const result = await api.getTopicFollowup(props.projectId, topicId)
    if (!active || seq !== followupGeneration || topicId !== props.topic.id) return
    candidates.value = result.candidates
    confirmations.value = result.confirmations
    followupReady.value = true
    focusedDiscussion.value = focusedRevision.value = null
    const discussion = route?.query.comment_id
      ? await api.getTopicDiscussion(props.projectId, topicId, route.query.comment_id)
      : null
    const revision = route?.query.revision
      ? await api.getTopicRevision(props.projectId, topicId, route.query.revision)
      : null
    if (!active || seq !== followupGeneration || topicId !== props.topic.id) return
    focusedDiscussion.value = discussion
    focusedRevision.value = revision
  } catch (failure) {
    if (active && seq === followupGeneration) followupError.value = describeBoardError(failure)
  }
}
async function refreshFollowup() {
  emit('updated')
  await Promise.all([loadMore(true), loadFollowup()])
}
async function openConfirmation(id) {
  await nextTick()
  const record = document.getElementById(`topic-confirmation-${id}`)
  if (record) {
    record.open = true
    record.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
}
async function loadMore(reset = false) {
  if (reset) generation += 1
  else if (loading.value) return
  const seq = generation
  const topicId = props.topic.id
  loading.value = true
  try {
    const result = await api.getTopicTimeline(
      props.projectId,
      topicId,
      reset ? null : nextBefore.value
    )
    if (seq !== generation || topicId !== props.topic.id) return
    events.value = reset ? result.items : [...events.value, ...result.items]
    nextBefore.value = result.next_before
  } catch (failure) {
    if (seq === generation) error.value = describeBoardError(failure)
  } finally {
    if (seq === generation) loading.value = false
  }
}
async function perform(callback, refresh = true) {
  busy.value = true
  error.value = ''
  try {
    await callback()
    if (!active) return
    emit('updated')
    if (refresh) await loadMore(true)
  } catch (failure) {
    if (active) {
      error.value = describeBoardError(failure)
      if ([401, 403, 404].includes(failure?.status || failure?.response?.status)) emit('visibility-lost', failure)
    }
  } finally {
    if (active) busy.value = false
  }
}
async function operate() {
  if (['resubmit', 'reopen', 'close', 'delete'].includes(action.value) && !reason.value.trim()) {
    error.value = '请填写操作原因'
    return
  }
  if (action.value === 'decide' && !decisionId.value) {
    error.value = '请选择当前议题已批准的关联决策'
    return
  }
  if (action.value === 'reopen' && !executionHint.value) {
    error.value = '请选择原方案继续执行或建议暂停'
    return
  }
  if (action.value === 'delete' && content.value.trim()) {
    error.value = '请先发布或清空讨论草稿，再删除议题'
    return
  }
  if (action.value === 'delete') {
    const confirmed = await new Promise((resolve) => {
      cancelDeleteConfirmation = () => resolve(false)
      deleteConfirmation = Modal.confirm({
        title: '确认删除此议题？',
        content: '删除后将无法在页面查看或恢复；已关联决策或任务的议题无法删除。',
        okText: '删除',
        okType: 'danger',
        cancelText: '取消',
        onOk: () => resolve(true),
        onCancel: () => resolve(false)
      })
    })
    deleteConfirmation = cancelDeleteConfirmation = undefined
    if (!active || !confirmed) return
  }
  return perform(async () => {
    await api.operateTopic(props.projectId, props.topic.id, {
      action: action.value,
      reason: reason.value,
      execution_hint: executionHint.value || null,
      decision_id: decisionId.value || null
    })
    reason.value = ''
    action.value = undefined
  }, action.value !== 'delete')
}
const restore = () =>
  perform(() => api.operateTopic(props.projectId, props.topic.id, { action: 'restore' }))
const post = () => {
  const submitted = content.value
  return perform(async () => {
    const intent = stableIntent(props.draft, {
      content: submitted,
      discussion_type: discussionType.value
    })
    await api.createTopicComment(props.projectId, props.topic.id, submitted, discussionType.value, {
      operation_id: intent.operation_id
    })
    if (active) consumeIntent(props.draft, intent.operation_id)
    if (active && content.value === submitted) content.value = ''
  })
}
watch(
  () => [props.projectId, props.topic.id],
  (_current, previous) => {
    generation += 1
    events.value = []
    nextBefore.value = null
    if (previous) {
      action.value = decisionId.value = executionHint.value = undefined
      reason.value = ''
    }
    error.value = ''
    followupReady.value = false
    focusedDiscussion.value = focusedRevision.value = null
    void loadFollowup()
    void loadMore(true)
  },
  { immediate: true }
)
watch(
  () => [
    props.topic.revision_number,
    props.topic.admission_status,
    props.topic.progress,
    props.topic.archived_at
  ],
  () => {
    void loadMore(true)
    void loadFollowup()
  }
)
watch(
  () => [route?.query.comment_id, route?.query.revision],
  () => {
    void loadFollowup()
  }
)
</script>

<style scoped>
summary { cursor: pointer; min-height: 36px; color: var(--gray-700); }
.source-work-link {
  color: var(--main-color);
}
.topic-history,
.topic-maintenance,
.topic-discussion {
  display: grid;
  gap: 12px;
}
.history-event {
  border-top: 1px solid var(--gray-150);
  padding: 16px 0;
}
.history-event header {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
.history-event header span,
.topic-discussion span {
  color: var(--color-text-secondary);
  font-size: 12px;
}
.history-event details {
  margin-top: 12px;
}
</style>
