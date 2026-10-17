<template>
  <section class="topic-history" :class="{ 'continuous-history': presentation === 'continuous' }">
    <template v-if="presentation === 'continuous' && !maintenanceOpen"><a-alert v-if="error" type="error" show-icon :message="error"><template #action><a-button @click="loadMore(true)">重试动态</a-button></template></a-alert><a-alert v-if="followupError" type="error" show-icon :message="followupError"><template #action><a-button @click="loadFollowup">重试讨论与确认</a-button></template></a-alert></template>
    <component :is="presentation === 'continuous' ? Modal : 'div'" :open="maintenanceOpen" :title="themeText('议题维护与实际达成')" :footer="null" :width="720" @cancel="maintenanceOpen = false">
    <a-alert
      v-if="topic.execution_hint"
      show-icon
      :type="topic.execution_hint === 'pause_recommended' ? 'warning' : 'info'"
      :message="topic.execution_hint === 'pause_recommended' ? '建议暂停原方案' : '原方案继续执行'"
      :description="themeText('此提示仅记录议题意见，不暂停关联任务或执行记录，也不撤销正式决策。')"
    />
    <p>{{ themeText('纳入议题不等于批准决策。正文修改保留修订，不覆盖正式决策。') }}</p>
    <RouterLink
      class="source-work-link"
      v-if="!topic.archived_at"
      :to="{
        name: 'ProjectWorkTasksView',
        params: { project_id: projectId },
        query: { create: '1', topic_id: topic.id }
      }"
      >{{ themeText('从此议题创建工作') }}</RouterLink
    >
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <details v-if="!topic.archived_at" :open="presentation === 'continuous' || !!action" class="topic-maintenance">
      <summary v-if="presentation !== 'continuous'">{{ themeText('议题维护（关闭、重开、归档等）') }}</summary>
      <a-select v-model:value="action" :aria-label="themeText('议题操作')" style="min-width: 160px">
        <a-select-option v-if="topic.admission_status === 'rejected'" value="resubmit"
          >重新提交纳入</a-select-option
        >
        <a-select-option
          v-if="topic.admission_status === 'canonical' && topic.progress === 'open'"
          value="decide"
          >标记已形成决策</a-select-option
        >
        <a-select-option v-if="topic.progress !== 'closed'" value="close">{{ themeText('关闭议题') }}</a-select-option>
        <a-select-option v-if="topic.progress !== 'open'" value="reopen">{{ themeText('重开议题') }}</a-select-option>
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
      <p v-if="action === 'decide'">{{ themeText('确认后将清除本议题的继续执行或建议暂停提示；任务和执行记录保持各自状态。') }}</p>
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
        :aria-label="themeText('议题操作原因')"
        :maxlength="100000"
      />
      <p v-if="action === 'delete'">{{ themeText('删除后，议题将从页面移除。已关联决策或任务的议题无法删除，请使用归档。') }}</p>
      <a-button :danger="action === 'delete'" :disabled="busy || !action" @click="operate">{{
        actionLabel
      }}</a-button>
    </details>
    <a-button v-else :disabled="busy" @click="restore">{{ themeText('恢复归档议题') }}</a-button>
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
    </component>
    <article v-if="focusedRevision" class="history-event">
      <h4>定位历史修订 {{ focusedRevision.number }}</h4>
      <h5>{{ focusedRevision.title }}</h5>
      <MarkdownPreview :content="focusedRevision.summary || '暂无正文'" /><MarkdownPreview
        :content="`${focusedRevision.expected_outcome || '未填写预期结果'}\n\n${focusedRevision.verification_conditions || '未填写核对条件'}`"
      />
    </article>
    <article v-if="focusedDiscussion && presentation !== 'continuous'" class="history-event">
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
    <component :is="presentation === 'continuous' ? 'div' : 'details'" :open="presentation === 'continuous' || !!route?.query.comment_id || !!route?.query.revision">
    <summary v-if="presentation !== 'continuous'">历史时间线 · {{ events.length }} 个已加载节点</summary>
    <div v-if="presentation === 'continuous'" class="activity-heading"><h2>动态</h2><div class="timeline-tools"><button v-for="item in [['all','全部'],['discussion','讨论'],['work','执行'],['history','历史']]" :key="item[0]" :aria-pressed="eventFilter === item[0]" :class="{ active: eventFilter === item[0] }" @click="eventFilter = item[0]">{{ item[1] }}</button><select v-model="eventOrder" aria-label="动态顺序"><option value="asc">由早到晚</option><option value="desc">最新在前</option></select></div></div>
    <a-spin v-if="loading" />
    <p v-if="!loading && !events.length && !error">暂无历史节点。</p>
    <article v-for="event in displayedEvents" :key="event.key || event.sequence" :id="event.comment ? `topic-discussion-${event.comment.id}` : undefined" :tabindex="event.comment ? -1 : undefined" class="history-event" :class="{ 'discussion-event': !!event.comment, 'work-event': event.kind === 'work' }">
      <div v-if="event.kind === 'work'" class="timeline-work"><RouterLink :to="{name:'ProjectWorkTaskView',params:{project_id:projectId,task_id:event.work.id}}"><strong>{{ event.work.title }}</strong><p>{{ event.work.description?.slice(0,180) }}</p></RouterLink><span>{{ event.work.number }} · {{ overviewStatusLabel(event.work.status) }}</span></div>
      <header v-else-if="presentation !== 'continuous' || !event.comment">
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
        <router-link :to="{ query: { ...$route.query, decision_id: event.details.decision_id, comment_id: undefined, revision: undefined } }"
          >查看决策详情</router-link
        >
      </p>
      <router-link
        v-if="event.kind === 'reply' || event.kind === 'disposition'"
        :to="{
          query: {
            ...$route.query,
            decision_id: undefined,
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
      <details v-if="event.comment && (presentation === 'continuous' || event.comment.id !== focusedDiscussion?.id)" :open="presentation !== 'continuous' || expandedThreads.has(event.comment.id) || route?.query.comment_id === event.comment.id" class="timeline-discussion" @toggle="rememberThread(event.comment.id, $event)"><summary><strong>{{ event.comment.author_name || '讨论' }}</strong><span class="discussion-kind">{{ discussionLabels[event.comment.discussion_type] || '研讨' }}</span><span class="thread-preview">{{ (event.comment.content || '').slice(0,80) }}</span><time>{{ timestampLabel(event.created_at) }}</time></summary>
      <TopicDiscussionCard
        :project-id="projectId"
        :topic-id="topic.id"
        :comment="event.comment"
        :candidates="candidates"
        :archived="!!topic.archived_at"
        :draft="draft"
        @updated="refreshFollowup"
      @visibility-lost="failure => emit('visibility-lost', failure)"
      />
      </details>
      <small v-if="event.comment && !event.revision_number">当时正文版本未知</small>
      <details v-if="event.revision">
        <summary>
          查看当时正文 · 修订 {{ event.revision.number
          }}{{ event.revision.origin === 'migration' ? '（迁移基线）' : '' }}
        </summary>
        <section class="revision-snapshot" :aria-label="`修订 ${event.revision.number} 正文快照`">
          <div class="revision-snapshot-heading"><span>历史正文 · 修订 {{ event.revision.number }}</span><span>只读</span></div>
          <h3>{{ event.revision.title }}</h3>
          <div class="revision-snapshot-prose"><MarkdownPreview :content="event.revision.summary || '暂无正文'" /></div>
          <div class="revision-snapshot-conditions"><section><h4>预期结果</h4><MarkdownPreview :content="event.revision.expected_outcome || '未填写预期结果'" /></section><section><h4>核对条件</h4><MarkdownPreview :content="event.revision.verification_conditions || '未填写核对条件'" /></section></div>
        </section>
      </details>
    </article>
    <a-button v-if="nextBefore" :disabled="loading" @click="loadMore(false)">加载更早记录</a-button>
    </component>
    <div v-if="!topic.archived_at" class="topic-discussion">
      <h4 v-if="presentation !== 'continuous'">持续研讨</h4>
      <a-textarea
        v-model:value="content"
        :maxlength="100000"
        :auto-size="{ minRows: 5, maxRows: 20 }"
        aria-label="发表讨论"
        placeholder="留下讨论、证据或反馈…"
      />
      <div class="composer-actions">
      <a-select v-model:value="discussionType" aria-label="讨论类型" style="min-width: 140px">
        <a-select-option value="discussion">研讨</a-select-option>
        <a-select-option value="reconsideration">重议</a-select-option>
        <a-select-option value="correction">纠偏</a-select-option>
      </a-select>
      <a-button :disabled="busy || !content.trim()" @click="post">{{ presentation === 'continuous' ? '发表' : '发布讨论' }}</a-button>
      </div>
      <span v-if="presentation !== 'continuous'">{{ themeText('讨论类型表达意图，发帖不会自动重开议题。') }}</span>
    </div>
  </section>
</template>

<script setup>
import { useProjectThemeVocabulary } from '@/composables/useProjectThemeVocabulary'
const { themeText } = useProjectThemeVocabulary()

import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { computed, nextTick, onBeforeUnmount, reactive, ref, toRef, watch } from 'vue'
import { useRoute } from 'vue-router'
import { consumeIntent, stableIntent } from '@/utils/topicFollowup'
import TopicDiscussionCard from './TopicDiscussionCard.vue'
import TopicOutcomePanel from './TopicOutcomePanel.vue'
import { Modal } from 'ant-design-vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { describeBoardError, overviewStatusLabel } from '@/utils/governanceBoard'

const props = defineProps({
  projectId: { type: String, required: true },
  topic: { type: Object, required: true },
  decisions: { type: Array, default: () => [] },
  presentation: { type: String, default: 'history' },
  works: { type: Array, default: () => [] },
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
const maintenanceOpen = ref(false)
defineExpose({ openMaintenance: () => { maintenanceOpen.value = true } })
const events = ref([])
const eventFilter = ref('all'), eventOrder = ref('asc')
const displayedEvents = computed(() => {
  if (props.presentation !== 'continuous') return events.value
  const sourceEvents = [...events.value]
  if (focusedDiscussion.value && !sourceEvents.some(item => item.comment?.id === focusedDiscussion.value.id)) sourceEvents.push({ kind: 'comment', key: `comment:${focusedDiscussion.value.id}`, comment: focusedDiscussion.value, created_at: focusedDiscussion.value.created_at })
  const rows = [...sourceEvents, ...props.works.map(work => ({ kind: 'work', key: `work:${work.id}`, work, created_at: work.created_at }))]
  return rows.filter(event => eventFilter.value === 'all' || (event.kind === 'work' ? 'work' : event.comment ? 'discussion' : 'history') === eventFilter.value)
    .sort((a, b) => (Date.parse(a.created_at) - Date.parse(b.created_at) || (a.sequence || 0) - (b.sequence || 0)) * (eventOrder.value === 'asc' ? 1 : -1))
})
const expandedThreads = ref(new Set(props.draft.expandedThreads || []))
function rememberThread(id, event) {
  const values = new Set(expandedThreads.value)
  if (event.target.open) values.add(id)
  else values.delete(id)
  expandedThreads.value = values
  sharedDraft.expandedThreads = [...values]
}
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
useProjectThemeEdit(() => themeText('议题讨论与维护'), () => props.projectId, () => Boolean(content.value?.trim() || reason.value?.trim() || action.value || decisionId.value || executionHint.value), () => {Object.assign(sharedDraft,{content:'',reason:'',action:undefined,decisionId:undefined,executionHint:undefined})}, () => busy.value, true)
const actionLabel = computed(
  () =>
    ({
      resubmit: '重新提交纳入',
      decide: '确认已形成决策',
      close: themeText('关闭议题'),
      reopen: themeText('重开议题'),
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
    : themeText(labels[event.kind] || event.kind)
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
    if (discussion && props.presentation === 'continuous') {
      eventFilter.value = 'all'
      await nextTick()
      const target = typeof document === 'undefined' ? null : document.getElementById(`topic-discussion-${discussion.id}`)
      target?.scrollIntoView({ block: 'center' })
      target?.focus({ preventScroll: true })
    }
  } catch (failure) {
    if (active && seq === followupGeneration) {
      followupError.value = describeBoardError(failure)
      if ([401, 403, 404].includes(failure?.status || failure?.response?.status)) {
        candidates.value = []; confirmations.value = []; focusedDiscussion.value = focusedRevision.value = null
        emit('visibility-lost', failure)
      }
    }
  }
}
async function refreshFollowup() {
  emit('updated')
  await Promise.all([loadMore(true), loadFollowup()])
}
async function openConfirmation(id) {
  maintenanceOpen.value = true
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
    error.value = ''
    events.value = reset ? result.items : [...events.value, ...result.items]
    nextBefore.value = result.next_before
  } catch (failure) {
    if (seq === generation) {
      error.value = describeBoardError(failure)
      if ([401, 403, 404].includes(failure?.status || failure?.response?.status)) {
        events.value = []; nextBefore.value = null
        emit('visibility-lost', failure)
      }
    }
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
    error.value = themeText('请选择当前议题已批准的关联决策')
    return
  }
  if (action.value === 'reopen' && !executionHint.value) {
    error.value = '请选择原方案继续执行或建议暂停'
    return
  }
  if (action.value === 'delete' && content.value.trim()) {
    error.value = themeText('请先发布或清空讨论草稿，再删除议题')
    return
  }
  if (action.value === 'delete') {
    const confirmed = await new Promise((resolve) => {
      cancelDeleteConfirmation = () => resolve(false)
      deleteConfirmation = Modal.confirm({
        title: themeText('确认删除此议题？'),
        content: themeText('删除后将无法在页面查看或恢复；已关联决策或任务的议题无法删除。'),
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

<style scoped lang="less">
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

.timeline-tools { display:flex; gap:8px; margin:16px 0; > :deep(.ant-select) { min-width:120px; } }
.timeline-work { padding:16px; background:var(--gray-25); border:1px solid var(--gray-150); border-radius:8px; a { display:block; color:var(--color-text); text-decoration:none; } a:hover strong { color:var(--main-color); } p { font-size:14px; line-height:1.6; } span { font-size:12px; color:var(--color-text-secondary); } }
.timeline-discussion { margin-top:8px; summary { cursor:pointer; line-height:1.8; overflow-wrap:anywhere; } }

.continuous-history { display:block; border-top:1px solid var(--gray-150); padding-top:22px; .activity-heading { display:flex; align-items:center; justify-content:space-between; gap:15px; flex-wrap:wrap; margin-bottom:20px; h2 { margin:0; font-size:18px; } } .timeline-tools { margin:0; display:flex; align-items:center; gap:6px; flex-wrap:wrap; button { font-size:12px; border:0; background:none; padding:5px 8px; min-height:32px; color:var(--color-text-secondary); border-radius:6px; cursor:pointer; } button.active { color:var(--main-color); background:var(--main-10); } select { font-size:11px; border:0; padding:5px; background:transparent; color:var(--color-text-secondary); } }
.history-event { border:0; padding:5px 8px; margin-bottom:16px; font-size:13px; header { align-items:center; gap:10px; strong { font-weight:400; } span { margin-left:auto; font-size:11px; } } >p { font-size:12px; color:var(--color-text-secondary); } >details:not(.timeline-discussion) { font-size:11px; margin-top:4px; >summary { min-height:24px; } } }
.discussion-event { padding:0; }.timeline-discussion { background:var(--gray-0); border:1px solid var(--gray-150); border-radius:9px; margin:0; overflow:hidden; >summary { display:flex; align-items:center; list-style:none; gap:12px; padding:17px 18px; font-size:13px; min-width:0; >strong { white-space:nowrap; font-weight:500; } time { white-space:nowrap; font-size:11px; color:var(--color-text-secondary); } } &[open] .thread-preview { display:none; } :deep(.discussion-card) { padding:0 22px 20px; border:0; } }.thread-preview { flex:1; white-space:nowrap; text-overflow:ellipsis; overflow:hidden; color:var(--color-text-secondary); }.discussion-kind { color:var(--color-text-secondary); font-size:11px; }.work-event { padding:0; }.timeline-work { padding:17px 20px; background:var(--gray-0); border:1px solid var(--gray-150); border-left:3px solid var(--main-color); border-radius:7px; strong { font-size:15px; } p { font-size:12px; color:var(--color-text-secondary); margin:6px 0 10px; } }
.topic-discussion { margin-top:24px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:9px; padding:14px; gap:8px; :deep(textarea) { border:0; background:transparent; padding:4px; min-height:100px; } }.composer-actions { display:flex; gap:8px; align-items:center; justify-content:flex-end; :deep(.ant-select-selector) { border:0; background:transparent; box-shadow:none!important; } }
}
@media(max-width:760px) { .continuous-history .timeline-discussion >summary { gap:8px; flex-wrap:wrap; padding:14px; .thread-preview { flex-basis:100%; order:5; white-space:normal; } } }

.continuous-history { border-top:0; padding-top:0; .activity-heading { padding:0 4px 12px; border-bottom:1px solid var(--gray-150); margin-bottom:20px; } .history-event:not(.discussion-event):not(.work-event) { margin-left:8px; border-left:2px solid var(--gray-150); padding:8px 14px; color:var(--color-text-secondary); } .timeline-discussion>summary { font-size:14px; } .timeline-discussion>summary>strong { font-weight:600; color:var(--color-text); } }

/* 每条历史快照有完整外框，展开后的正文不与下一条动态相连。 */
.revision-snapshot { margin:12px 0 20px; padding:20px 24px; border:1px solid var(--gray-150); border-radius:8px; background:var(--gray-0); color:var(--color-text); font-size:15px; line-height:1.8; min-width:0; overflow-wrap:anywhere; }
.revision-snapshot-heading { display:flex; justify-content:space-between; gap:12px; padding-bottom:12px; margin-bottom:16px; border-bottom:1px solid var(--gray-150); font-size:12px; color:var(--color-text-secondary); }
.revision-snapshot>h3 { font-size:18px; line-height:1.6; margin:0 0 18px; color:var(--color-text); }
.revision-snapshot-conditions { margin-top:24px; padding-top:18px; border-top:1px solid var(--gray-150); display:grid; gap:16px; h4 { margin:0 0 8px; font-size:13px; font-weight:600; color:var(--color-text-secondary); } }
.revision-snapshot :deep(.yk-markdown-preview) { font-size:15px; line-height:1.8; }
@media(max-width:760px) { .revision-snapshot { padding:16px; margin-bottom:18px; }.revision-snapshot>h3 { font-size:17px; } }
</style>
