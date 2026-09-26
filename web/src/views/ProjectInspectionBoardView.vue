<template>
  <div class="inspection-page">
    <PageHeader :title="pageTitle" :loading="loading" show-border>
      <template #actions>
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
        <div class="workbench-links">
          <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'projects' } }"
            >配置项目数字员工</RouterLink
          >
          <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'schedules' } }"
            >配置定时汇报</RouterLink
          >
        </div>

        <section class="workbench-section">
          <h2>项目蓝图</h2>
          <div class="form-row">
            <a-select
              v-model:value="blueprintName"
              :disabled="busy || loading"
              style="min-width: 200px"
              @change="readBlueprint"
            >
              <a-select-option v-for="doc in blueprints" :key="doc.name" :value="doc.name">{{
                doc.name
              }}</a-select-option>
            </a-select>
            <a-input
              v-model:value="newBlueprintName"
              placeholder="新文档名，例如 plan.md"
              style="max-width: 240px"
            />
            <a-button :disabled="busy || loading" @click="startBlueprint">新建</a-button>
          </div>
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
            ><span
              v-if="newBlueprintPending || blueprintContent !== savedBlueprintContent"
              class="hint"
              >有未保存的蓝图草稿</span
            ><span v-else class="hint">保存后从项目 Workdir 回读。</span>
          </div>
        </section>

        <section class="workbench-section">
          <h2>议题与决策</h2>
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
              ><a-tag>{{ topic.status }}</a-tag
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

        <section class="workbench-section">
          <h2>任务与本地执行</h2>
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
              ><a-tag>{{ task.status }}</a-tag
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

        <section class="workbench-section">
          <h2>督查与汇报</h2>
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
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import GovernanceBoardPanel from '@/components/inspection/GovernanceBoardPanel.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import { describeBoardError } from '@/utils/governanceBoard'

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
const blueprintContent = ref('')
const loadedBlueprintName = ref('')
const savedBlueprintContent = ref('')
const newBlueprintPending = ref(false)
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
let blueprintReadSeq = 0
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

async function readBlueprint() {
  if (!blueprintName.value) return
  if (newBlueprintPending.value) {
    blueprintName.value = loadedBlueprintName.value
    actionError.value = '新蓝图尚未保存，请先保存后切换文档'
    return
  }
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    blueprintName.value = loadedBlueprintName.value
    actionError.value = '蓝图有未保存的修改，请先保存后切换文档'
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
    actionError.value = describeBoardError(error)
  }
}

async function load() {
  const project = projectId.value
  const seq = ++loadSeq
  loading.value = true
  errorMessage.value = ''
  try {
    const [nextBoard, docs, agentView, items] = await Promise.all([
      api.getProjectBoard(project),
      api.listBlueprints(project),
      projectAgentApi.list(project),
      api.listDelegations(project)
    ])
    if (seq !== loadSeq || projectId.value !== project) return
    board.value = nextBoard
    blueprints.value = docs.documents || []
    agents.value = agentView.agents || []
    delegations.value = items
    if (!blueprintName.value && blueprints.value.length)
      blueprintName.value = blueprints.value[0].name
    if (
      blueprintName.value &&
      !newBlueprintPending.value &&
      blueprintContent.value === savedBlueprintContent.value
    ) {
      if (blueprints.value.some((doc) => doc.name === blueprintName.value)) await readBlueprint()
      else {
        blueprintName.value = blueprints.value[0]?.name || ''
        if (blueprintName.value) await readBlueprint()
      }
    }
  } catch (error) {
    if (seq === loadSeq && projectId.value === project)
      errorMessage.value = describeBoardError(error)
  } finally {
    if (seq === loadSeq && projectId.value === project) loading.value = false
  }
}

async function act(operation) {
  busy.value = true
  actionError.value = ''
  try {
    await operation()
    await load()
  } catch (error) {
    actionError.value = describeBoardError(error)
  } finally {
    busy.value = false
  }
}

function startBlueprint() {
  if (loadedBlueprintName.value && blueprintContent.value !== savedBlueprintContent.value) {
    actionError.value = '蓝图有未保存的修改，请先保存后新建文档'
    return
  }
  const name = newBlueprintName.value.trim()
  if (!/^[a-z0-9][a-z0-9._-]*\.md$/.test(name)) {
    actionError.value = '文档名需为小写单层 .md 文件名'
    return
  }
  if (blueprints.value.some((doc) => doc.name === name)) {
    actionError.value = '蓝图已存在，请从列表选择并编辑'
    return
  }
  blueprintReadSeq += 1
  blueprintName.value = name
  blueprintContent.value = ''
  savedBlueprintContent.value = ''
  loadedBlueprintName.value = name
  newBlueprintPending.value = true
  newBlueprintName.value = ''
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
    newBlueprintPending.value = false
  })
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
  blueprintName.value = ''
  loadedBlueprintName.value = ''
  blueprintContent.value = ''
  savedBlueprintContent.value = ''
  newBlueprintPending.value = false
  load()
})
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
  gap: 16px;
  padding: var(--page-padding);
}
.inspection-state {
  margin: 40px auto;
}
.workbench-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}
.workbench-section h2 {
  margin: 0;
  font-size: 16px;
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
  gap: 16px;
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
</style>
