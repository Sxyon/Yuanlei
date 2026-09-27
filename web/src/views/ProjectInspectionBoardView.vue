<template>
  <div class="inspection-page">
    <PageHeader :title="pageTitle" :loading="loading" show-border>
      <template #actions>
        <a-button
          size="small"
          @click="router.push({ name: 'ProjectDashboardComp', params: { project_id: projectId } })"
          >项目概览</a-button
        >
        <a-button size="small" @click="router.push({ name: 'InspectionBoardComp' })"
          >返回督查板</a-button
        >
        <a-button size="small" :disabled="loading || busy" @click="load">刷新</a-button>
      </template>
    </PageHeader>

    <div class="inspection-body">
      <a-spin v-if="loading" class="inspection-state" />
      <a-alert
        v-else-if="errorMessage"
        type="error"
        show-icon
        message="项目工作台加载失败"
        :description="errorMessage"
      >
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <template v-else>
        <a-alert
          v-if="actionError"
          type="error"
          show-icon
          :message="actionError"
          closable
          @close="actionError = ''"
        />
        <header class="workbench-intro">
          <div>
            <p class="workbench-kicker">PROJECT WORKBENCH</p>
            <h1>{{ board.project?.name || '项目工作台' }}</h1>
            <p>维护蓝图，审核议题和任务，发起执行并查看汇报。</p>
          </div>
          <div class="workbench-links">
            <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'projects' } }"
              >项目数字员工</RouterLink
            >
            <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'schedules' } }"
              >定时汇报</RouterLink
            >
          </div>
        </header>
        <nav class="workbench-nav" aria-label="工作台栏目">
          <button
            v-for="item in sectionLinks"
            :key="item.id"
            type="button"
            @click="jumpTo(item.id)"
          >
            {{ item.label }}
          </button>
        </nav>

        <section id="blueprint" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">01</span>
            <div>
              <h2>项目蓝图</h2>
              <p>记录目标、范围和验收标准</p>
            </div>
          </div>
          <a-alert
            v-if="blueprintActionError"
            type="error"
            show-icon
            :message="blueprintActionError"
            closable
            @close="blueprintActionError = ''"
          />
          <div class="form-row">
            <a-select
              v-model:value="blueprintName"
              :disabled="busy || loading"
              placeholder="选择当前蓝图"
              style="min-width: 200px"
              @change="readBlueprint"
            >
              <a-select-option v-for="doc in blueprints" :key="doc.name" :value="doc.name">{{
                displayBlueprintName(doc.name)
              }}</a-select-option>
            </a-select>
            <a-input
              v-model:value="newBlueprintName"
              aria-label="新蓝图名称"
              placeholder="新蓝图名称，例如 product-plan"
              style="max-width: 240px"
              @pressEnter="createBlueprint"
            />
            <a-button :disabled="busy || loading" @click="createBlueprint">新建蓝图</a-button>
          </div>
          <p class="hint">名称使用小写字母、数字、点、下划线或短横线；系统自动补全 .md。</p>
          <a-textarea
            v-model:value="blueprintContent"
            :rows="9"
            :disabled="!blueprintName"
            placeholder="在这里编辑项目目标、范围、验收标准与执行计划"
          />
          <div class="form-row">
            <a-button
              type="primary"
              :disabled="!blueprintName || blueprintName !== loadedBlueprintName || busy || loading"
              @click="saveBlueprint"
              >保存蓝图</a-button
            ><span v-if="blueprintContent !== savedBlueprintContent" class="hint"
              >有未保存的蓝图草稿</span
            ><span v-else class="hint">保存后从项目 Workdir 回读。</span>
            <a-popconfirm
              v-if="blueprintName"
              title="归档后可在下方历史蓝图翻阅，确认归档？"
              ok-text="归档"
              cancel-text="取消"
              @confirm="archiveBlueprint"
              ><a-button :disabled="busy || loading">归档当前蓝图</a-button></a-popconfirm
            >
          </div>
          <div class="blueprint-history">
            <h3>
              历史蓝图 <span>{{ archivedBlueprints.length }}</span>
            </h3>
            <p v-if="!archivedBlueprints.length" class="hint">
              暂无归档蓝图。旧蓝图归档后会在这里保留供翻阅。
            </p>
            <div v-else class="archive-layout">
              <div class="archive-list" aria-label="历史蓝图列表">
                <button
                  v-for="archive in archivedBlueprints"
                  :key="archive.archive_name"
                  type="button"
                  :class="{ active: selectedArchive === archive.archive_name }"
                  @click="readArchive(archive.archive_name)"
                >
                  <strong>{{ displayBlueprintName(archive.name) }}</strong
                  ><small>{{ archiveTimeLabel(archive.archived_at) }}</small>
                </button>
              </div>
              <div class="archive-preview">
                <a-spin v-if="archiveLoading" />
                <a-alert v-else-if="archiveError" type="error" show-icon :message="archiveError" />
                <MarkdownPreview v-else-if="archiveContent" :content="archiveContent" />
                <p v-else class="hint">选择一份历史蓝图查看内容。</p>
              </div>
            </div>
          </div>
        </section>

        <section id="topics" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">02</span>
            <div>
              <h2>议题与决策</h2>
              <p>提出问题、审核议题并形成结论</p>
            </div>
          </div>
          <div class="form-row">
            <a-input v-model:value="topicTitle" placeholder="议题标题" /><a-input
              v-model:value="topicSummary"
              placeholder="背景与待解决的问题"
            /><a-button :disabled="!topicTitle.trim() || busy" @click="createTopic"
              >提出议题</a-button
            >
          </div>
          <ul class="workbench-list">
            <li v-for="topic in board.governance?.topics || []" :key="topic.id">
              <strong>{{ topic.title }}</strong
              ><a-tag :color="governanceStatusColor(topic.status)">{{
                governanceStatusLabel(topic.status)
              }}</a-tag
              ><span>{{ topic.summary }}</span>
              <a-button
                v-if="topic.status === 'proposed'"
                size="small"
                :disabled="busy"
                @click="reviewTopic(topic, true)"
                >通过</a-button
              >
              <a-button
                v-if="topic.status === 'proposed'"
                size="small"
                :disabled="busy"
                @click="reviewTopic(topic, false)"
                >拒绝</a-button
              >
            </li>
          </ul>
          <div class="form-row">
            <a-input v-model:value="decisionTitle" placeholder="决策标题" /><a-select
              v-model:value="decisionTopicId"
              allow-clear
              placeholder="关联议题"
              style="min-width: 180px"
              ><a-select-option
                v-for="topic in canonicalTopics"
                :key="topic.id"
                :value="topic.id"
                >{{ topic.title }}</a-select-option
              ></a-select
            >
          </div>
          <a-textarea
            v-model:value="decisionConclusion"
            :rows="2"
            placeholder="明确结论与执行方向"
          />
          <div class="form-row">
            <a-button
              :disabled="!decisionTitle.trim() || !decisionConclusion.trim() || busy"
              @click="createDecision"
              >记录决策</a-button
            >
          </div>
          <ul class="workbench-list">
            <li v-for="decision in board.governance?.decisions || []" :key="decision.id">
              <strong>{{ decision.title }}</strong
              ><span>{{ decision.conclusion }}</span>
            </li>
          </ul>
        </section>

        <section id="tasks" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">03</span>
            <div>
              <h2>任务与本地执行</h2>
              <p>审核任务并追踪委派结果</p>
            </div>
          </div>
          <div class="form-row">
            <a-input v-model:value="taskTitle" placeholder="任务标题" /><a-select
              v-model:value="taskAgentSlug"
              allow-clear
              placeholder="项目数字员工"
              style="min-width: 180px"
              ><a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{
                agent.name || agent.slug
              }}</a-select-option></a-select
            >
          </div>
          <a-textarea
            v-model:value="taskDescription"
            :rows="3"
            placeholder="交付物、验收条件和工作范围"
          />
          <div class="form-row">
            <a-select
              v-model:value="taskDecisionId"
              allow-clear
              placeholder="关联决策"
              style="min-width: 180px"
              ><a-select-option
                v-for="decision in board.governance?.decisions || []"
                :key="decision.id"
                :value="decision.id"
                >{{ decision.title }}</a-select-option
              ></a-select
            ><a-button :disabled="!taskTitle.trim() || busy" @click="createTask"
              >创建待审核任务</a-button
            >
          </div>
          <ul class="workbench-list">
            <li v-for="task in board.governance?.tasks || []" :key="task.id">
              <strong>{{ task.title }}</strong
              ><a-tag :color="governanceStatusColor(task.status)">{{
                governanceStatusLabel(task.status)
              }}</a-tag
              ><span>{{ task.assignee_agent_slug || '未指派' }}</span>
              <a-button
                v-if="task.status === 'proposed'"
                size="small"
                :disabled="busy"
                @click="reviewTask(task, true)"
                >通过</a-button
              >
              <a-button
                v-if="task.status === 'proposed'"
                size="small"
                :disabled="busy"
                @click="reviewTask(task, false)"
                >拒绝</a-button
              >
              <template v-if="task.status === 'canonical' && task.assignee_agent_slug">
                <a-select v-model:value="executorKey" style="width: 120px"
                  ><a-select-option value="codex">Codex</a-select-option
                  ><a-select-option value="opencode">OpenCode</a-select-option></a-select
                >
                <a-button size="small" :disabled="busy" @click="delegateTask(task)"
                  >委派执行</a-button
                >
              </template>
              <ul v-if="taskDelegations(task.id).length" class="delegation-list">
                <li v-for="item in taskDelegations(task.id)" :key="item.operation_id">
                  {{ item.executor_key }} · {{ item.remote_status || item.dispatch_state }}
                  <span v-if="item.error_code"> · {{ item.error_code }}</span>
                  <a-button
                    v-if="item.dispatch_state === 'dispatched'"
                    size="small"
                    :disabled="busy"
                    @click="refreshDelegation(item)"
                    >查状态</a-button
                  >
                  <a-button
                    v-if="item.dispatch_state === 'dispatched' && terminalTurn(item.remote_status)"
                    size="small"
                    :disabled="busy"
                    @click="collectDelegation(item)"
                    >回收</a-button
                  >
                  <p v-if="item.result?.summary">{{ item.result.summary }}</p>
                  <p v-if="item.artifact_path">产物：{{ item.artifact_path }}</p>
                </li>
              </ul>
            </li>
          </ul>
        </section>

        <section id="reports" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">04</span>
            <div>
              <h2>督查与汇报</h2>
              <p>查看待处理事项、阻塞执行和项目汇报</p>
            </div>
          </div>
          <GovernanceBoardPanel :board="board" />
          <ul class="workbench-list">
            <li v-for="report in board.governance?.reports || []" :key="report.id">
              <strong>{{ report.title }}</strong
              ><span>{{ report.summary }}</span
              ><span v-if="report.artifact_path">{{ report.artifact_path }}</span>
            </li>
          </ul>
        </section>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import GovernanceBoardPanel from '@/components/inspection/GovernanceBoardPanel.vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { displayBlueprintName, normalizeBlueprintName } from '@/utils/blueprintName'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import {
  describeBoardError,
  governanceStatusColor,
  governanceStatusLabel
} from '@/utils/governanceBoard'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => String(route.params.project_id || ''))
const loading = ref(false)
const busy = ref(false)
const errorMessage = ref('')
const actionError = ref('')
const board = ref({ project: null, governance: null, execution: null })
const blueprints = ref([])
const blueprintName = ref('')
const newBlueprintName = ref('')
const blueprintActionError = ref('')
const blueprintContent = ref('')
const loadedBlueprintName = ref('')
const savedBlueprintContent = ref('')
const archivedBlueprints = ref([])
const selectedArchive = ref('')
const archiveContent = ref('')
const archiveError = ref('')
const archiveLoading = ref(false)
const agents = ref([])
const delegations = ref([])
const topicTitle = ref('')
const topicSummary = ref('')
const decisionTitle = ref('')
const decisionConclusion = ref('')
const decisionTopicId = ref(undefined)
const taskTitle = ref('')
const taskDescription = ref('')
const taskDecisionId = ref(undefined)
const taskAgentSlug = ref(undefined)
const executorKey = ref('codex')
const sectionLinks = [
  { id: 'blueprint', label: '项目蓝图' },
  { id: 'topics', label: '议题与决策' },
  { id: 'tasks', label: '任务与执行' },
  { id: 'reports', label: '督查与汇报' }
]
const jumpTo = (id) =>
  document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
let blueprintReadSeq = 0
let archiveReadSeq = 0
let loadSeq = 0
const pageTitle = computed(() =>
  board.value?.project?.name ? `${board.value.project.name} · 项目工作台` : '项目工作台'
)
const canonicalTopics = computed(() =>
  (board.value.governance?.topics || []).filter((item) => item.status === 'canonical')
)
const taskDelegations = (taskId) =>
  delegations.value.filter((item) => item.governance_task_id === taskId)
const terminalTurn = (status) =>
  ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
const archiveTimeLabel = (raw) => {
  const value = String(raw || '')
  if (!/^\d{8}T\d{12}Z$/.test(value)) return value
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T${value.slice(9, 11)}:${value.slice(11, 13)}:${value.slice(13, 15)}.${value.slice(15, 18)}Z`
  return new Date(iso).toLocaleString('zh-CN')
}

async function readBlueprint() {
  if (!blueprintName.value) return
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    blueprintName.value = loadedBlueprintName.value
    blueprintActionError.value = '蓝图有未保存的修改，请先保存后切换文档'
    return
  }
  const name = blueprintName.value
  const project = projectId.value
  const seq = ++blueprintReadSeq
  try {
    const document = await api.getBlueprint(project, name)
    if (seq !== blueprintReadSeq || blueprintName.value !== name || projectId.value !== project)
      return
    blueprintContent.value = document.content
    savedBlueprintContent.value = document.content
    loadedBlueprintName.value = document.name
  } catch (error) {
    if (seq !== blueprintReadSeq || blueprintName.value !== name || projectId.value !== project)
      return
    blueprintName.value = loadedBlueprintName.value
    blueprintActionError.value = describeBoardError(error)
  }
}

async function readArchive(name) {
  const project = projectId.value
  const seq = ++archiveReadSeq
  selectedArchive.value = name
  archiveLoading.value = true
  archiveError.value = ''
  archiveContent.value = ''
  try {
    const document = await api.getBlueprintArchive(project, name)
    if (seq !== archiveReadSeq || projectId.value !== project) return
    archiveContent.value = document.content
  } catch (error) {
    if (seq !== archiveReadSeq || projectId.value !== project) return
    archiveError.value = describeBoardError(error)
  } finally {
    if (seq === archiveReadSeq && projectId.value === project) archiveLoading.value = false
  }
}

async function load() {
  const project = projectId.value
  const seq = ++loadSeq
  loading.value = true
  errorMessage.value = ''
  try {
    const [boardResult, docsResult, archiveResult, agentResult, delegationResult] =
      await Promise.allSettled([
        api.getProjectBoard(project),
        api.listBlueprints(project),
        api.listBlueprintArchives(project),
        projectAgentApi.list(project),
        api.listDelegations(project)
      ])
    if (seq !== loadSeq || projectId.value !== project) return
    if (boardResult.status === 'rejected') throw boardResult.reason
    board.value = boardResult.value
    agents.value = agentResult.status === 'fulfilled' ? agentResult.value.agents || [] : []
    delegations.value = delegationResult.status === 'fulfilled' ? delegationResult.value : []
    const auxiliaryErrors = [docsResult, archiveResult, agentResult, delegationResult]
      .filter((result) => result.status === 'rejected')
      .map((result) => describeBoardError(result.reason))
    if (auxiliaryErrors.length)
      actionError.value = `部分工作台数据加载失败：${auxiliaryErrors.join('；')}`
    if (archiveResult.status === 'fulfilled')
      archivedBlueprints.value = archiveResult.value.documents || []
    if (docsResult.status === 'fulfilled') {
      blueprints.value = docsResult.value.documents || []
      if (!blueprintName.value && blueprints.value.length)
        blueprintName.value = blueprints.value[0].name
      if (blueprintName.value && blueprintContent.value === savedBlueprintContent.value) {
        if (blueprints.value.some((doc) => doc.name === blueprintName.value)) await readBlueprint()
        else {
          blueprintName.value = blueprints.value[0]?.name || ''
          if (blueprintName.value) await readBlueprint()
        }
      }
      if (!blueprints.value.length) {
        blueprintName.value = ''
        loadedBlueprintName.value = ''
        blueprintContent.value = ''
        savedBlueprintContent.value = ''
      }
    }
  } catch (error) {
    if (seq === loadSeq && projectId.value === project)
      errorMessage.value = describeBoardError(error)
  } finally {
    if (seq === loadSeq && projectId.value === project) loading.value = false
  }
}

async function act(operation, errorTarget = actionError) {
  busy.value = true
  errorTarget.value = ''
  try {
    await operation()
    await load()
  } catch (error) {
    errorTarget.value = describeBoardError(error)
  } finally {
    busy.value = false
  }
}

function createBlueprint() {
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    blueprintActionError.value = '蓝图有未保存的修改，请先保存后新建文档'
    return
  }
  const raw = newBlueprintName.value.trim()
  const name = normalizeBlueprintName(raw)
  if (!name) {
    blueprintActionError.value = '蓝图名称需使用英文小写字母、数字、点、下划线或短横线'
    return
  }
  if (blueprints.value.some((doc) => doc.name === name)) {
    blueprintActionError.value = '蓝图已存在，请从列表选择并编辑'
    return
  }
  act(async () => {
    const content = `# ${displayBlueprintName(name)}\n`
    const created = await api.createBlueprint(projectId.value, name, content)
    blueprintReadSeq += 1
    blueprintName.value = created.name
    loadedBlueprintName.value = created.name
    blueprintContent.value = created.content
    savedBlueprintContent.value = created.content
    newBlueprintName.value = ''
  }, blueprintActionError)
}
const saveBlueprint = () =>
  act(async () => {
    const document = await api.putBlueprint(
      projectId.value,
      loadedBlueprintName.value,
      blueprintContent.value
    )
    savedBlueprintContent.value = document.content
    loadedBlueprintName.value = document.name
  }, blueprintActionError)
const archiveBlueprint = () => {
  if (blueprintContent.value !== savedBlueprintContent.value) {
    blueprintActionError.value = '蓝图有未保存的修改，请先保存后归档'
    return
  }
  act(async () => {
    const archived = await api.archiveBlueprint(projectId.value, blueprintName.value)
    blueprintReadSeq += 1
    blueprintName.value = ''
    loadedBlueprintName.value = ''
    blueprintContent.value = ''
    savedBlueprintContent.value = ''
    await readArchive(archived.archive_name)
  }, blueprintActionError)
}
const createTopic = () =>
  act(async () => {
    await api.createTopic(projectId.value, { title: topicTitle.value, summary: topicSummary.value })
    topicTitle.value = ''
    topicSummary.value = ''
  })
const reviewTopic = (topic, approve) =>
  act(() => api.reviewTopic(projectId.value, topic.id, approve))
const createDecision = () =>
  act(async () => {
    await api.createDecision(projectId.value, {
      title: decisionTitle.value,
      conclusion: decisionConclusion.value,
      topic_id: decisionTopicId.value || null
    })
    decisionTitle.value = ''
    decisionConclusion.value = ''
  })
const createTask = () =>
  act(async () => {
    await api.createTask(projectId.value, {
      title: taskTitle.value,
      description: taskDescription.value,
      decision_id: taskDecisionId.value || null,
      assignee_agent_slug: taskAgentSlug.value || null
    })
    taskTitle.value = ''
    taskDescription.value = ''
  })
const reviewTask = (task, approve) => act(() => api.reviewTask(projectId.value, task.id, approve))
const delegateTask = (task) =>
  act(() => api.delegateTask(projectId.value, task.id, executorKey.value))
const refreshDelegation = (item) =>
  act(async () => {
    await api.getDelegation(projectId.value, item.operation_id)
  })
const collectDelegation = (item) =>
  act(() => api.collectDelegation(projectId.value, item.operation_id))

watch(projectId, () => {
  blueprintReadSeq += 1
  archiveReadSeq += 1
  blueprints.value = []
  archivedBlueprints.value = []
  selectedArchive.value = ''
  archiveContent.value = ''
  archiveError.value = ''
  archiveLoading.value = false
  agents.value = []
  delegations.value = []
  blueprintName.value = ''
  loadedBlueprintName.value = ''
  blueprintContent.value = ''
  savedBlueprintContent.value = ''
  blueprintActionError.value = ''
  load()
})
watch(
  [loading, () => route.hash],
  async ([isLoading, hash]) => {
    if (isLoading || !hash || !sectionLinks.some((item) => `#${item.id}` === hash)) return
    await nextTick()
    jumpTo(hash.slice(1))
  },
  { immediate: true }
)
onMounted(load)
</script>

<style scoped lang="less">
.inspection-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.inspection-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: 18px;
  padding: var(--page-padding);
  background: var(--gray-25);
}
.workbench-intro {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 26px 28px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}
.workbench-kicker {
  margin: 0 0 8px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.workbench-intro h1 {
  margin: 0;
  color: var(--gray-1000);
  font-size: 25px;
}
.workbench-intro p:last-child {
  margin: 8px 0 0;
  color: var(--gray-600);
}
.workbench-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.workbench-nav button {
  padding: 7px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-700);
  cursor: pointer;
}
.workbench-nav button:hover {
  border-color: var(--main-color);
  color: var(--main-color);
}
.inspection-state {
  margin: 40px auto;
}
.workbench-section {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 24px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
  scroll-margin-top: 16px;
}
.section-heading {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--gray-100);
}
.section-index {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 7px;
  background: var(--main-30);
  color: var(--main-color);
  font-size: 12px;
  font-weight: 700;
}
.section-heading h2 {
  margin: 0;
  font-size: 17px;
  color: var(--gray-1000);
}
.section-heading p {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}
.workbench-section h2 {
  color: var(--gray-1000);
}
.form-row,
.workbench-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.form-row > .ant-input {
  flex: 1;
  min-width: 180px;
}
.workbench-links {
  gap: 8px;
}
.workbench-links a {
  padding: 7px 10px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  font-size: 13px;
  color: var(--gray-700);
  text-decoration: none;
}
.workbench-links a:visited,
.workbench-links a:hover,
.workbench-links a:active {
  color: var(--gray-700);
  text-decoration: none;
}
.workbench-links a:hover {
  border-color: var(--main-color);
}
.workbench-list > li {
  align-items: flex-start;
}
.workbench-list > li > strong {
  min-width: 150px;
}
.workbench-list > li > span:not(.ant-tag) {
  color: var(--gray-600);
  overflow-wrap: anywhere;
}
@media (max-width: 680px) {
  .workbench-intro {
    align-items: flex-start;
    flex-direction: column;
    padding: 20px;
  }
  .workbench-section {
    padding: 18px;
  }
}
.workbench-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 8px;
}
.workbench-list > li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
}
.workbench-list strong {
  color: var(--gray-1000);
}
.delegation-list {
  flex-basis: 100%;
  margin: 0;
  padding-left: 20px;
}
.delegation-list li {
  margin: 6px 0;
}
.delegation-list p {
  margin: 4px 0;
  overflow-wrap: anywhere;
}
.hint {
  color: var(--gray-500);
  font-size: 12px;
}
.blueprint-history {
  padding-top: 16px;
  border-top: 1px solid var(--gray-100);
}
.blueprint-history h3 {
  margin: 0 0 12px;
  color: var(--gray-900);
  font-size: 15px;
}
.blueprint-history h3 span {
  margin-left: 5px;
  color: var(--gray-500);
  font-size: 12px;
}
.archive-layout {
  display: grid;
  grid-template-columns: minmax(170px, 220px) minmax(0, 1fr);
  gap: 14px;
}
.archive-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 300px;
  overflow: auto;
}
.archive-list button {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--gray-150);
  border-radius: 7px;
  background: var(--gray-0);
  color: var(--gray-800);
  cursor: pointer;
  text-align: left;
}
.archive-list button.active {
  border-color: var(--main-color);
  background: var(--main-30);
}
.archive-list small {
  color: var(--gray-500);
}
.archive-preview {
  min-width: 0;
  min-height: 180px;
  max-height: 360px;
  overflow: auto;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 7px;
  background: var(--gray-25);
}
@media (max-width: 680px) {
  .archive-layout {
    grid-template-columns: 1fr;
  }
}
</style>
