<template>
  <section class="decision-panel">
    <p>草案可修改；批准后原文保留。补充保留原决策有效，整条替代才使原决策失效。</p>
    <p v-if="!decisions.length">还没有决策记录。</p>
    <article
      v-for="decision in currentDecisions"
      :id="`decision-${decision.id}`"
      :key="decision.id"
      class="decision-card"
    >
      <header>
        <strong>{{ decision.title }}</strong
        ><a-tag :color="governanceStatusColor(decision.status)">{{
          governanceStatusLabel(decision.status)
        }}</a-tag>
      </header>
      <p>{{ relationLabels[decision.relation_type] }} · 版本 {{ decision.revision_number }}</p>
      <a-alert
        v-if="decision.requires_review"
        type="warning"
        show-icon
        message="原依据已变化，需复核"
      />
      <a-alert
        v-if="decision.topic_execution_hint === 'pause_recommended'"
        type="warning"
        show-icon
        message="关联议题建议暂停原方案"
        description="仅为业务提示，不暂停任务或执行记录。"
      />
      <MarkdownPreview :content="decision.conclusion" />
      <a-button @click="open(decision)">查看决策与历史</a-button>
      <RouterLink class="source-work-link" v-if="decision.status === 'approved'" :to="workLink(decision)">创建工作</RouterLink>
    </article>
    <details :open="historicalSelected">
      <summary>历史决策（{{ historicalDecisions.length }} 条）</summary>
      <article
        v-for="decision in historicalDecisions"
        :id="`decision-${decision.id}`"
        :key="decision.id"
        class="decision-card"
      >
        <strong>{{ decision.title }}</strong
        ><a-tag>{{ governanceStatusLabel(decision.status) }}</a-tag>
        <a-button @click="open(decision)">查看原文与历史</a-button>
      </article>
    </details>
    <section v-if="selected" class="decision-detail">
      <h3>{{ selected.title }} · {{ governanceStatusLabel(selected.status) }}</h3>
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <a-spin v-if="loading" />
      <template v-if="detail">
        <a-alert
          v-if="detail.requires_review"
          type="warning"
          show-icon
          message="原依据已变化，需复核。此补充不自动成为新的整体方案。"
        />
        <RouterLink class="source-work-link" v-if="detail.status === 'approved'" :to="workLink(detail)">基于此决策创建工作</RouterLink>
        <p v-if="detail.topic_id">
          关联议题：<a @click="$emit('topic', detail.topic_id)">{{
            topics.find((t) => t.id === detail.topic_id)?.title || detail.topic_id
          }}</a>
        </p>
        <p v-if="detail.target">
          {{ relationLabels[detail.relation_type] }}目标：<a @click="open(detail.target)"
            >{{ detail.target.title }}（{{ governanceStatusLabel(detail.target.status) }}）</a
          >
        </p>
        <p v-for="related in detail.related_decisions" :key="related.id">
          {{ relationLabels[related.relation_type] }}：<a @click="open(related)"
            >{{ related.title }}（{{ governanceStatusLabel(related.status) }}）</a
          >
        </p>
        <p v-if="detail.references.length">已有引用：{{ detail.references.join('、') }}</p>
        <p v-for="task in detail.tasks" :key="task.id">
          已关联治理任务：<router-link :to="{ query: { ...$route.query, task_id: task.id } }">{{
            task.title
          }}</router-link>
          · {{ governanceStatusLabel(task.status) }}
        </p>
        <h4>{{ detail.status === 'draft' ? '当前草案' : '批准原文' }}</h4>
        <MarkdownPreview :content="`${detail.conclusion}\n\n---\n\n${detail.rationale || ''}`" />
        <p v-if="detail.decided_at">
          批准人 {{ detail.decided_by }} · {{ timestampLabel(detail.decided_at) }} · 议题依据版本
          {{ detail.topic_revision_number || (detail.topic_id ? '旧依据版本未知' : '无关联议题') }}
        </p>
        <article v-for="erratum in detail.errata" :key="erratum.id" class="history-node">
          <strong>文字勘误 · {{ fieldLabels[erratum.field] }}</strong>
          <p>原文：{{ erratum.original_text }}</p>
          <p>勘误：{{ erratum.corrected_text }}</p>
          <p>
            {{ erratum.reason }} · {{ erratum.author_name }} ·
            {{ timestampLabel(erratum.created_at) }} · 版本 {{ erratum.revision_number }}
          </p>
        </article>
        <div class="actions">
          <a-button v-if="detail.status === 'draft'" @click="beginEdit">修改草案</a-button>
          <a-button v-if="detail.status === 'draft'" @click="chooseAction('approve')"
            >批准决策</a-button
          >
          <a-button v-if="detail.status === 'draft'" danger @click="chooseAction('delete')"
            >删除草案</a-button
          >
          <a-button v-if="detail.status === 'approved'" danger @click="chooseAction('revoke')"
            >撤销决策</a-button
          >
          <a-button v-if="detail.status !== 'draft'" @click="chooseAction('erratum')"
            >追加文字勘误</a-button
          >
          <a-button
            v-if="detail.status === 'approved'"
            @click="$emit('compose', detail, 'supplement')"
            >新增补充草案</a-button
          >
          <a-button
            v-if="detail.status === 'approved'"
            @click="$emit('compose', detail, 'replacement')"
            >新增整条替代草案</a-button
          >
        </div>
        <form v-if="action" @submit.prevent="submit">
          <a-alert
            v-if="action === 'approve'"
            type="info"
            message="批准仅记录正式依据；确认议题需单独操作，不改变任务或执行记录。"
          />
          <a-alert
            v-if="
              action === 'approve' &&
              topics.find((t) => t.id === detail.topic_id)?.admission_status !== 'canonical' &&
              detail.topic_id
            "
            type="warning"
            message="来源议题尚未纳入，请核对；此提示不阻止批准。"
          />
          <section
            v-if="action === 'approve' && detail.relation_type === 'replacement'"
            class="replacement-confirmation"
          >
            <a-alert
              type="warning"
              show-icon
              message="确认整条替代：批准后原决策将被替代，不再作为当前有效依据。"
            />
            <h5>原决策：{{ detail.target?.title }}</h5>
            <MarkdownPreview :content="detail.target?.conclusion || ''" />
            <h5>新决策：{{ detail.title }}</h5>
            <MarkdownPreview :content="detail.conclusion" />
          </section>
          <template v-if="action === 'edit'">
            <a-input v-model:value="draft.title" aria-label="草案标题" :maxlength="512" />
            <a-textarea
              v-model:value="draft.conclusion"
              aria-label="草案结论"
              :maxlength="100000"
              :auto-size="{ minRows: 5, maxRows: 20 }"
            />
            <a-textarea
              v-model:value="draft.rationale"
              aria-label="草案理由"
              :maxlength="100000"
              :auto-size="{ minRows: 3, maxRows: 15 }"
            />
            <a-select
              v-model:value="draft.relation_type"
              aria-label="草案形成方式"
              @change="draft.target_decision_id = null"
            >
              <a-select-option
                v-for="(label, value) in relationLabels"
                :key="value"
                :value="value"
                >{{ label }}</a-select-option
              >
            </a-select>
            <a-select
              v-if="draft.relation_type !== 'ordinary'"
              v-model:value="draft.target_decision_id"
              aria-label="草案目标决策"
            >
              <a-select-option
                v-for="target in approvedTargets"
                :key="target.id"
                :value="target.id"
                >{{ target.title }}</a-select-option
              >
            </a-select>
            <p>冲突时以下草稿会保留，可选中文字复制。</p>
            <details>
              <summary>复制完整草稿</summary>
              <a-textarea :value="JSON.stringify(draft, null, 2)" readonly />
            </details>
          </template>
          <template v-if="action === 'erratum'">
            <a-alert
              type="info"
              message="只修正不改变业务含义的文字错误。数值、范围、条件变化请新增补充或整条替代决策。批准原文不会覆盖。"
            />
            <a-select v-model:value="erratum.field" aria-label="勘误字段"
              ><a-select-option v-for="(label, value) in fieldLabels" :key="value" :value="value">{{
                label
              }}</a-select-option></a-select
            >
            <a-textarea
              v-model:value="erratum.original_text"
              placeholder="批准原文中的文字"
              :maxlength="100000"
            />
            <a-textarea
              v-model:value="erratum.corrected_text"
              placeholder="修正文字"
              :maxlength="100000"
            />
            <a-checkbox v-model:checked="erratum.meaning_unchanged"
              >我确认此勘误不改变业务含义</a-checkbox
            >
          </template>
          <a-textarea
            v-model:value="reason"
            aria-label="决策操作原因"
            placeholder="操作原因（必填）"
            :maxlength="100000"
          />
          <p v-if="!reason.trim()">请填写操作原因。</p>
          <a-button
            html-type="submit"
            :loading="busy"
            :disabled="!reason.trim() || (action === 'erratum' && !erratum.meaning_unchanged)"
            >{{ actionLabels[action] }}</a-button
          >
          <a-button :disabled="busy" @click="cancel">取消</a-button>
        </form>
        <h4>决策局部时间线 · 最新在前</h4>
        <article v-for="event in events" :key="event.sequence" class="history-node">
          <strong
            >{{ eventLabels[event.kind] || event.kind }} · 版本 {{ event.revision_number }}</strong
          >
          <p>
            {{ event.author_name || event.created_by || '迁移基线' }} ·
            {{ timestampLabel(event.created_at) }}
          </p>
          <p>{{ event.reason }}</p>
          <a
            v-if="event.details.related_decision_id"
            @click="openById(event.details.related_decision_id)"
            >查看关联新决策</a
          >
          <details>
            <summary>
              查看当时快照{{ event.origin === 'migration' ? '（迁移基线，过往修订未知）' : '' }}
            </summary>
            <h5>{{ event.snapshot.title }}</h5>
            <MarkdownPreview
              :content="`${event.snapshot.conclusion}\n\n${event.snapshot.rationale || ''}`"
            />
            <p>
              形成方式：{{ relationLabels[event.snapshot.relation_type] }} · 议题依据版本
              {{
                event.snapshot.topic_revision_number ||
                (event.snapshot.topic_id ? '旧依据版本未知' : '无关联议题')
              }}
            </p>
          </details>
        </article>
        <a-button v-if="nextBefore" :disabled="loading" @click="loadMore"
          >加载更早决策记录</a-button
        >
      </template>
    </section>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Modal } from 'ant-design-vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { governanceStatusColor, governanceStatusLabel } from '@/utils/governanceBoard'

const workLink = (decision) => ({ name: 'ProjectWorkTasksView', params: { project_id: props.projectId },
  query: { create: '1', source_decision_id: decision.id, ...(decision.topic_id ? { topic_id: decision.topic_id } : {}) } })
const props = defineProps({
  projectId: { type: String, required: true },
  decisions: { type: Array, default: () => [] },
  topics: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' }
})
const emit = defineEmits(['updated', 'select', 'compose', 'topic'])
const timestampLabel = (raw) => (raw ? new Date(raw).toLocaleString('zh-CN') : '')
const relationLabels = { ordinary: '普通决策', supplement: '补充决策', replacement: '整条替代' }
const fieldLabels = { title: '标题', conclusion: '结论', rationale: '理由' }
const actionLabels = {
  edit: '保存草案',
  approve: '确认批准',
  revoke: '确认撤销',
  delete: '删除草案',
  erratum: '保存文字勘误'
}
const eventLabels = {
  created: '新增草案',
  revised: '修订草案',
  approved: '批准决策',
  supplemented: '批准补充',
  superseded: '整条被替代',
  revoked: '撤销决策',
  deleted: '删除草案',
  erratum: '追加文字勘误',
  migration_baseline: '迁移基线'
}
const currentDecisions = computed(() =>
  props.decisions.filter((d) => ['draft', 'approved'].includes(d.status))
)
const historicalDecisions = computed(() =>
  props.decisions.filter((d) => ['superseded', 'revoked'].includes(d.status))
)
const historicalSelected = computed(() =>
  historicalDecisions.value.some((d) => d.id === props.selectedId)
)
const selected = ref(null),
  detail = ref(null),
  events = ref([]),
  nextBefore = ref(null)
const loading = ref(false),
  busy = ref(false),
  error = ref(''),
  action = ref(''),
  reason = ref('')
const draft = ref({}),
  erratum = ref({
    field: 'conclusion',
    original_text: '',
    corrected_text: '',
    meaning_unchanged: false
  })
const approvedTargets = computed(() =>
  props.decisions.filter((d) => d.status === 'approved' && d.id !== selected.value?.id)
)
let generation = 0
let deleteConfirmation
onBeforeUnmount(() => {
  generation++
  deleteConfirmation?.destroy()
})
function cancel() {
  action.value = ''
  error.value = ''
}
function chooseAction(value) {
  if (busy.value) return false
  if (action.value) {
    error.value = '当前表单尚未保存，请先保存或取消。'
    return false
  }
  action.value = value
  reason.value = ''
  error.value = ''
  erratum.value = {
    field: 'conclusion',
    original_text: '',
    corrected_text: '',
    meaning_unchanged: false
  }
  return true
}
function beginEdit() {
  if (!chooseAction('edit')) return
  draft.value = {
    title: detail.value.title,
    conclusion: detail.value.conclusion,
    rationale: detail.value.rationale || '',
    topic_id: detail.value.topic_id,
    relation_type: detail.value.relation_type,
    target_decision_id: detail.value.target_decision_id,
    expected_revision: detail.value.revision_number
  }
}
async function open(decision) {
  if (busy.value) return
  if (action.value) {
    error.value = '当前表单尚未保存，请先保存或取消；草稿仍可复制。'
    return
  }
  selected.value = decision
  detail.value = null
  events.value = []
  nextBefore.value = null
  error.value = ''
  action.value = ''
  emit('select', decision.id)
  const seq = ++generation
  loading.value = true
  try {
    const result = await api.getDecision(props.projectId, decision.id)
    if (seq !== generation) return
    detail.value = result
    selected.value = result
    events.value = result.timeline
    nextBefore.value = result.next_before
  } catch (e) {
    if (seq === generation) error.value = e?.message || '读取决策失败'
  } finally {
    if (seq === generation) loading.value = false
  }
}
function openById(id) {
  const decision = props.decisions.find((d) => d.id === id)
  if (decision) open(decision)
}
async function loadMore() {
  if (loading.value || !nextBefore.value) return
  const seq = generation,
    id = selected.value.id
  loading.value = true
  try {
    const result = await api.getDecision(props.projectId, id, nextBefore.value)
    if (seq !== generation) return
    events.value.push(...result.timeline)
    nextBefore.value = result.next_before
  } catch (e) {
    if (seq === generation) error.value = e?.message || '读取历史失败'
  } finally {
    if (seq === generation) loading.value = false
  }
}
async function submit() {
  if (busy.value || !reason.value.trim()) return
  if (action.value === 'delete') {
    const seq = generation
    deleteConfirmation = Modal.confirm({
      title: '删除草案？',
      content: '删除后从页面移除；已有引用的草案无法删除。',
      okText: '删除',
      cancelText: '取消',
      okType: 'danger',
      onOk: () => {
        if (seq === generation && action.value === 'delete') return perform()
      }
    })
  } else await perform()
}
async function perform() {
  busy.value = true
  error.value = ''
  const seq = generation
  const id = selected.value.id,
    operation = action.value
  try {
    if (operation === 'edit')
      await api.updateDecision(props.projectId, id, { ...draft.value, reason: reason.value })
    else if (operation === 'erratum')
      await api.createDecisionErratum(props.projectId, id, {
        ...erratum.value,
        reason: reason.value,
        expected_revision: detail.value.revision_number
      })
    else
      await api.operateDecision(props.projectId, id, {
        action: operation,
        expected_revision: detail.value.revision_number,
        reason: reason.value
      })
    if (seq !== generation) return
    action.value = ''
    emit('updated')
    busy.value = false
    if (operation === 'delete') {
      generation++
      selected.value = null
      detail.value = null
      emit('select', '')
    } else await open({ id })
  } catch (e) {
    if (seq === generation) error.value = e?.message || '操作失败，草稿已保留'
  } finally {
    if (seq === generation) busy.value = false
  }
}
watch(
  () => props.selectedId,
  (id) => {
    if (id && id !== selected.value?.id) openById(id)
  },
  { immediate: true }
)
watch(
  () => props.decisions,
  () => {
    if (props.selectedId && !selected.value) openById(props.selectedId)
  }
)
watch(
  () => props.projectId,
  () => {
    generation++
    deleteConfirmation?.destroy()
    loading.value = false
    busy.value = false
    selected.value = null
    detail.value = null
    action.value = ''
    events.value = []
  }
)
</script>

<style scoped>
.source-work-link { color: var(--main-color); }
.decision-panel,
.decision-detail,
form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}
.decision-card,
.history-node,
.decision-detail {
  padding: 16px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  overflow-wrap: anywhere;
}
.decision-card header,
.actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  align-items: center;
}
</style>
