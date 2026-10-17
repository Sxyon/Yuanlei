<script setup>
import { useProjectThemeVocabulary } from '@/composables/useProjectThemeVocabulary'
const { themeText } = useProjectThemeVocabulary()

import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { inject, computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import WorkSuggestionsPanel from '@/components/project/WorkSuggestionsPanel.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { codingSessionApi } from '@/apis/coding_session_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import { useUserStore } from '@/stores/user'
import { describeBoardError } from '@/utils/governanceBoard'
import { getGovernanceDraft, setGovernanceDraft } from '@/utils/governanceDrafts'
const accessLost = inject('projectAccessLost', () => {})
const props = defineProps({ projectId: { type: String, required: true } })
const user = useUserStore(),
  route = useRoute()
const board = ref({}),
  agents = ref([]),
  delegations = ref([]),
  sessionDetails = ref({}),
  loading = ref(false),
  busy = ref(false),
  error = ref(''),
  search = ref(''),
  filter = ref('pending'),
  open = ref(false),
  draft = ref({})
useProjectThemeEdit('新建行动计划', () => props.projectId, () => Boolean(open.value && (draft.value.title || draft.value.description)), () => {open.value=false;draft.value={};setGovernanceDraft(user.uid,props.projectId,'theme-plan-create',null)}, () => busy.value, true)
let generation = 0
const suggestions = computed(() =>
  (board.value.tasks || []).filter(
    (item) =>
      `${item.title}\n${item.description || ''}`.includes(search.value) &&
      (filter.value === 'all' ||
        (filter.value === 'linked' && item.work) ||
        (filter.value === 'pending' && !item.work && item.status !== 'rejected'))
  )
)
const historyId = computed(() =>
  route.hash?.startsWith('#legacy-execution-') ? route.hash.slice(18) : ''
)
const focusedId = computed(() =>
  String(
    route.query.task_id ||
      historyId.value ||
      (route.hash?.startsWith('#task-') ? route.hash.slice(6) : '')
  )
)
async function focusSuggestion() {
  if (!focusedId.value) return
  filter.value = 'all'
  search.value = ''
  await nextTick()
  document
    .getElementById(
      historyId.value ? `legacy-execution-${historyId.value}` : `task-${focusedId.value}`
    )
    ?.scrollIntoView({ block: 'center' })
}
watch(focusedId, focusSuggestion)
const capture = () => ({ generation, project: props.projectId, user: user.uid })
const current = (token) =>
  token.generation === generation && token.project === props.projectId && token.user === user.uid
function failure(cause) {
  error.value = describeBoardError(cause)
  if ([401, 403, 404].includes(cause?.status || cause?.response?.status)) {
    board.value = {}
    agents.value = []
    delegations.value = []
    sessionDetails.value = {}
    open.value = false
    draft.value = {}
    setGovernanceDraft(user.uid, props.projectId, 'theme-plan-create', null)
    generation++
    loading.value = false
    accessLost()
  }
}
async function load() {
  const token = capture()
  loading.value = true
  error.value = ''
  try {
    const [value, staff, executions] = await Promise.all([
      api.getProjectBoard(token.project),
      projectAgentApi.list(token.project),
      api.listDelegations(token.project)
    ])
    if (!current(token)) return
    board.value = value.governance || {}
    agents.value = staff.agents || []
    delegations.value = executions
    await focusSuggestion()
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    if (current(token)) loading.value = false
  }
}
function create() {
  draft.value = getGovernanceDraft(user.uid, props.projectId, 'theme-plan-create') || {
    title: '',
    description: '',
    topic_id: null,
    decision_id: null,
    assignee_agent_slug: null
  }
  open.value = true
}
watch(
  draft,
  () => {
    if (open.value) setGovernanceDraft(user.uid, props.projectId, 'theme-plan-create', draft.value)
  },
  { deep: true }
)
async function submit() {
  if (busy.value || !draft.value.title?.trim()) return
  const token = capture()
  busy.value = true
  error.value = ''
  try {
    await api.createTask(token.project, { ...draft.value })
    if (current(token)) {
      setGovernanceDraft(token.user, token.project, 'theme-plan-create', null)
      open.value = false
      await load()
    }
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    if (current(token)) busy.value = false
  }
}
async function reject(item) {
  const token = capture()
  busy.value = true
  try {
    await api.reviewTask(token.project, item.id, false)
    if (current(token)) await load()
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    if (current(token)) busy.value = false
  }
}
const terminalTurn = (status) =>
  ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
const executionLabel = (item) =>
  ({
    queued: '等待派发',
    dispatching: '派发中',
    dispatched: '已派发',
    reclaimed: '已回收',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
    interrupted: '已中断'
  })[item.remote_status || item.dispatch_state] ||
  item.remote_status ||
  item.dispatch_state
const historicalTasks = computed(() =>
  (board.value.tasks || []).filter((task) =>
    delegations.value.some((item) => item.governance_task_id === task.id)
  )
)
async function inspectExecution(item, action) {
  const token = capture()
  busy.value = true
  error.value = ''
  try {
    if (action === 'detail') {
      const detail = await codingSessionApi.detail(item.session_id)
      if (current(token)) sessionDetails.value[item.session_id] = detail.session || detail
    } else {
      if (action === 'collect') await api.collectDelegation(token.project, item.operation_id)
      else await api.getDelegation(token.project, item.operation_id)
      if (current(token)) await load()
    }
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    if (current(token)) busy.value = false
  }
}
watch(
  () => [props.projectId, user.uid],
  () => {
    generation++
    board.value = {}
    agents.value = []
    delegations.value = []
    sessionDetails.value = {}
    open.value = false
    busy.value = false
    void load()
  },
  { immediate: true }
)
onBeforeUnmount(() => generation++)
</script>
<template>
  <section aria-label="行动计划工作区">
    <div class="collection-tools">
      <div class="plan-tabs"><button v-for="item in [['pending','待落实'],['linked','已关联工作']]" :key="item[0]" :aria-pressed="filter === item[0]" :class="{ active: filter === item[0] }" @click="filter = item[0]">{{ item[1] }} <span v-if="item[0] === 'pending'" class="count-badge">{{ (board.tasks || []).filter(row => !row.work && row.status !== 'rejected').length }}</span></button><details class="plan-search"><summary aria-label="筛选行动计划">···</summary><a-input v-model:value="search" aria-label="搜索行动计划" placeholder="搜索行动计划" allow-clear /><a-button type="text" @click="filter = 'all'">全部计划</a-button></details></div>
      <a-button type="primary" @click="create">新建</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <p v-if="loading" role="status">正在读取行动计划…</p>
    <a-alert
      v-if="focusedId && !loading && !(board.tasks || []).some((item) => item.id === focusedId)"
      type="warning"
      show-icon
      message="指定行动计划不存在或无权访问，原地址保留。"
    /><WorkSuggestionsPanel v-show="!loading"
      :project-id="projectId"
      :suggestions="suggestions"
      :topics="board.topics || []"
      :decisions="board.decisions || []"
      presentation="plans"
      :selected-id="focusedId"
      @reject="reject"
      @admitted="load"
      @visibility-lost="failure"
    />
    <details v-if="historicalTasks.length" class="execution-history" :open="Boolean(historyId)">
      <summary>历史执行记录 · {{ delegations.length }}</summary>
      <article v-for="task in historicalTasks" :key="task.id" :id="`legacy-execution-${task.id}`">
        <h3>{{ task.title }}</h3>
        <p>{{ task.assignee_agent_slug || '未指派' }}</p>
        <div
          v-for="item in delegations.filter((row) => row.governance_task_id === task.id)"
          :key="item.operation_id"
        >
          <p>
            {{ item.executor_key }} · {{ executionLabel(item) }}
            <span v-if="item.error_code">· {{ item.error_code }}</span>
          </p>
          <a-button
            v-if="item.dispatch_state === 'dispatched'"
            :disabled="busy"
            @click="inspectExecution(item, 'refresh')"
            >查状态</a-button
          >
          <a-button
            v-if="item.dispatch_state === 'dispatched' && terminalTurn(item.remote_status)"
            :disabled="busy"
            @click="inspectExecution(item, 'collect')"
            >回收</a-button
          >
          <p v-if="item.result?.summary">{{ item.result.summary }}</p>
          <p v-if="item.artifact_path">产物：{{ item.artifact_path }}</p>
          <a-button
            v-if="item.session_id"
            :disabled="busy"
            @click="inspectExecution(item, 'detail')"
            >查看执行详情</a-button
          >
          <p v-if="sessionDetails[item.session_id]">
            会话 {{ item.session_id }} · {{ sessionDetails[item.session_id].status }} ·
            {{ sessionDetails[item.session_id].error_code }}
            {{ sessionDetails[item.session_id].error_message }}
          </p>
        </div>
      </article>
    </details>
    <a-modal
      v-model:open="open"
      title="新建行动计划"
      :width="720"
      :mask-closable="false"
      :confirm-loading="busy"
      :closable="!busy"
      :cancel-button-props="{ disabled: busy }"
      ok-text="保存计划"
      cancel-text="保留草稿并关闭"
      @ok="submit"
      ><a-alert v-if="error" type="error" :message="error" /><a-form layout="vertical"
        ><a-form-item label="做什么" required
          ><a-input
            v-model:value="draft.title"
            aria-label="行动计划标题"
            :disabled="busy" /></a-form-item
        ><a-form-item label="预期结果与计划内容"
          ><a-textarea
            v-model:value="draft.description"
            aria-label="计划内容与预期结果"
            :auto-size="{ minRows: 8, maxRows: 18 }"
            :disabled="busy" /></a-form-item
        ><a-form-item :label="themeText('来源议题')"
          ><a-select v-model:value="draft.topic_id" allow-clear :aria-label="themeText('计划来源议题')"
            ><a-select-option v-for="item in board.topics || []" :key="item.id" :value="item.id">{{
              item.title
            }}</a-select-option></a-select
          ></a-form-item
        ><a-form-item label="来源决定"
          ><a-select v-model:value="draft.decision_id" allow-clear aria-label="计划来源决定"
            ><a-select-option
              v-for="item in board.decisions || []"
              :key="item.id"
              :value="item.id"
              >{{ item.title }}</a-select-option
            ></a-select
          ></a-form-item
        ><a-form-item label="建议承办智能体"
          ><a-select
            v-model:value="draft.assignee_agent_slug"
            allow-clear
            aria-label="建议承办智能体"
            ><a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{
              agent.name
            }}</a-select-option></a-select
          ></a-form-item
        ></a-form
      ></a-modal
    >
  </section>
</template>
<style scoped lang="less">
.execution-history {
  margin-top: 32px;
  article {
    padding: 20px 0;
    border-bottom: 1px solid var(--color-border);
  }
}
.collection-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 24px;
  > div {
    display: flex;
    gap: 8px;
    min-width: 0;
    :deep(.ant-input-affix-wrapper) {
      min-width: 80px;
      max-width: 360px;
    }
    :deep(.ant-select) {
      min-width: 120px;
    }
  }
}

.collection-tools { padding:20px 0; min-height:72px; margin-bottom:4px; }.plan-tabs { display:flex; gap:8px; align-items:center; >button { border:0; background:none; padding:8px 12px; min-height:40px; font-size:13px; color:var(--color-text-secondary); cursor:pointer; border-radius:7px; } >button.active { background:var(--main-10); color:var(--main-color); } }.count-badge { font-size:11px; border:1px solid var(--gray-150); border-radius:4px; margin-left:6px; padding:2px 6px; }.plan-search { position:relative; >summary { cursor:pointer; list-style:none; color:var(--color-text-secondary); } :deep(.ant-input-affix-wrapper) { position:absolute; top:32px; left:0; min-width:200px; z-index:3; } }
</style>
