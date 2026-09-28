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
            <RouterLink :to="{ name: 'ProjectWorkTasksView', params: { project_id: projectId } }"
              >项目工作任务</RouterLink
            >
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
          <p class="hint">支持中文、英文小写和数字，可含点、下划线或短横线；系统自动补全 .md。</p>
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
          <div v-if="topicComposerVisible" class="topic-composer">
            <div class="composer-heading">
              <div>
                <h3>提出新议题</h3>
                <p>用 Markdown 记录背景、目标、方案和待讨论的问题。</p>
              </div>
              <a-button :disabled="busy" @click="topicComposerVisible = false">收起</a-button>
            </div>
            <a-input v-model:value="topicDraftTitle" placeholder="议题标题" />
            <a-textarea
              v-model:value="topicDraftSummary"
              :maxlength="100000"
              :auto-size="{ minRows: 12, maxRows: 32 }"
              placeholder="## 背景\n\n描述问题、现状和影响。\n\n## 目标与方案\n\n列出目标、候选方案和需要讨论的事项。"
            />
            <div class="form-row">
              <a-button
                type="primary"
                :disabled="!topicDraftTitle.trim() || busy"
                @click="submitTopic"
                >创建议题并开始讨论</a-button
              >
              <span class="hint">正文支持 Markdown，单篇最多 100,000 字。</span>
            </div>
          </div>
          <a-alert v-if="topicCommentError" type="error" show-icon :message="topicCommentError" />
          <div class="topic-layout">
            <aside class="topic-sidebar">
              <div class="topic-sidebar-heading">
                <strong>议题列表</strong>
                <span>{{ allTopics.length }}</span>
                <a-button size="small" :disabled="busy" @click="topicComposerVisible = true">
                  提出议题
                </a-button>
              </div>
              <p v-if="!allTopics.length" class="hint topic-list-empty">还没有议题。</p>
              <article
                v-for="topic in allTopics"
                :key="topic.id"
                class="topic-list-card"
                :class="{ active: selectedTopicId === topic.id }"
              >
                <button type="button" class="topic-select" @click="selectTopic(topic)">
                  <span class="topic-list-title">{{ topic.title }}</span>
                  <a-tag :color="governanceStatusColor(topic.status)">{{
                    governanceStatusLabel(topic.status)
                  }}</a-tag>
                  <span class="topic-list-summary">{{ topic.summary || '暂无议题说明' }}</span>
                </button>
                <a-button size="small" :disabled="busy" @click="createDecisionFromTopic(topic)"
                  >新增决策</a-button
                >
              </article>
            </aside>

            <div v-if="selectedTopic" class="topic-detail">
              <header class="topic-detail-heading">
                <div>
                  <p class="eyebrow">议题详情</p>
                  <h3>{{ selectedTopic.title }}</h3>
                  <a-tag :color="governanceStatusColor(selectedTopic.status)">{{
                    governanceStatusLabel(selectedTopic.status)
                  }}</a-tag>
                </div>
                <a-button
                  v-if="selectedTopic.status === 'proposed' && !editingTopic"
                  :disabled="busy"
                  @click="beginEditTopic"
                  >修改提议</a-button
                >
              </header>

              <div v-if="editingTopic" class="topic-editor">
                <a-input v-model:value="editingTopicTitle" aria-label="议题标题" />
                <a-textarea
                  v-model:value="editingTopicSummary"
                  :maxlength="100000"
                  :auto-size="{ minRows: 16, maxRows: 36 }"
                  placeholder="使用 Markdown 编辑议题正文"
                />
                <div class="form-row">
                  <a-button type="primary" :disabled="!editingTopicTitle.trim() || busy" @click="saveTopicEdit"
                    >保存议题修改</a-button
                  >
                  <a-button :disabled="busy" @click="editingTopic = false">取消</a-button>
                </div>
              </div>
              <section v-else class="topic-proposal-body">
                <MarkdownPreview v-if="selectedTopic.summary" :content="selectedTopic.summary" />
                <p v-else class="hint">暂无议题说明。{{ selectedTopic.status === 'proposed' ? '可以先修改提议，补充背景和方案。' : '' }}</p>
              </section>

              <section class="discussion-thread">
                <div class="discussion-heading">
                  <div>
                    <h4>讨论</h4>
                    <p>补充问题、证据和不同意见，确认提议后再审核。</p>
                  </div>
                  <span>{{ topicComments.length }} 条回复</span>
                </div>
                <a-spin v-if="topicCommentsLoading" />
                <p v-else-if="!topicComments.length" class="discussion-empty">还没有回复，开始这场讨论。</p>
                <article v-for="comment in topicComments" :key="comment.id" class="discussion-post">
                  <header>
                    <strong>{{ comment.author_name || '项目成员' }}</strong>
                    <time>{{ timestampLabel(comment.created_at) }}</time>
                  </header>
                  <MarkdownPreview :content="comment.content" />
                </article>
                <div v-if="selectedTopic.status === 'proposed'" class="discussion-reply">
                  <a-textarea
                    v-model:value="commentDraft"
                    :maxlength="100000"
                    :auto-size="{ minRows: 8, maxRows: 24 }"
                    placeholder="写下讨论内容，支持 Markdown。"
                  />
                  <div class="form-row">
                    <a-button
                      type="primary"
                      :disabled="!commentDraft.trim() || busy"
                      @click="postTopicComment"
                      >发布回复</a-button
                    >
                    <span class="hint">议题审核通过或拒绝后，讨论串保留只读。</span>
                  </div>
                </div>
              </section>

              <footer v-if="selectedTopic.status === 'proposed' && !editingTopic" class="topic-review-actions">
                <div>
                  <strong>结束讨论并审核</strong>
                  <p>审核后议题正文和讨论串将保留为历史记录。</p>
                </div>
                <div class="form-row">
                  <a-button danger :disabled="busy" @click="reviewTopic(selectedTopic, false)">拒绝提议</a-button>
                  <a-button type="primary" :disabled="busy" @click="reviewTopic(selectedTopic, true)">
                    通过并结束讨论
                  </a-button>
                </div>
              </footer>
              <p v-else-if="selectedTopic.review?.reviewed_at" class="hint topic-review-note">
                {{ selectedTopic.status === 'canonical' ? '已通过' : '已拒绝' }} ·
                {{ timestampLabel(selectedTopic.review.reviewed_at) }}
                <span v-if="selectedTopic.review.note"> · {{ selectedTopic.review.note }}</span>
              </p>
            </div>
            <div v-else class="topic-detail-empty">
              <MessagesSquare :size="28" />
              <strong>选择一个议题查看详情</strong>
              <p>议题正文、讨论和审核操作会显示在这里。</p>
              <a-button type="primary" @click="topicComposerVisible = true">提出第一个议题</a-button>
            </div>
          </div>

          <div id="decision-entry" class="decision-entry">
            <div class="composer-heading">
              <div>
                <h3>新增决策</h3>
                <p>记录议题结论，并保留决策理由供后续执行和回顾。</p>
              </div>
              <a-tag v-if="decisionTopicId">已关联议题</a-tag>
            </div>
            <div class="form-row">
              <a-input v-model:value="decisionTitle" placeholder="决策标题" />
              <a-select
                v-model:value="decisionTopicId"
                allow-clear
                placeholder="关联议题"
                style="min-width: 220px"
              >
                <a-select-option v-for="topic in allTopics" :key="topic.id" :value="topic.id">
                  {{ topic.title }}
                </a-select-option>
              </a-select>
            </div>
            <a-textarea
              v-model:value="decisionConclusion"
              :auto-size="{ minRows: 8, maxRows: 24 }"
              placeholder="明确结论与执行方向，支持 Markdown。"
            />
            <a-textarea
              v-model:value="decisionRationale"
              :auto-size="{ minRows: 6, maxRows: 20 }"
              placeholder="决策理由、依据、风险与被否替代方案。"
            />
            <div class="form-row">
              <a-button
                type="primary"
                :disabled="!decisionTitle.trim() || !decisionConclusion.trim() || busy"
                @click="createDecision"
                >记录决策</a-button
              >
            </div>
          </div>
          <section id="decisions" class="decision-records">
            <div class="composer-heading">
              <div>
                <h3>已有决策</h3>
                <p>决策记录保留结论、理由和关联议题。</p>
              </div>
              <span class="hint">{{ board.governance?.decisions?.length || 0 }} 条</span>
            </div>
            <p v-if="!board.governance?.decisions?.length" class="hint">还没有决策记录。</p>
            <article
              v-for="decision in board.governance?.decisions || []"
              :id="`decision-${decision.id}`"
              :key="decision.id"
              class="decision-card"
              :class="{ 'selected-governance-item': route.query.decision_id === decision.id }"
            >
              <header>
                <strong>{{ decision.title }}</strong>
                <a-tag :color="governanceStatusColor(decision.status)">{{
                  governanceStatusLabel(decision.status)
                }}</a-tag>
              </header>
              <p v-if="topicTitleFor(decision.topic_id)" class="hint">
                关联议题：{{ topicTitleFor(decision.topic_id) }}
              </p>
              <MarkdownPreview :content="decisionDetail(decision)" />
            </article>
          </section>
        </section>

        <section id="tasks" class="workbench-section">
          <div class="section-heading">
            <span class="section-index">03</span>
            <div>
              <h2>治理审核任务与本地执行</h2>
              <p>这里处理治理审核任务；长期工作任务请前往项目工作任务管理。</p>
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
              v-model:value="taskTopicId"
              allow-clear
              placeholder="关联议题"
              style="min-width: 180px"
            >
              <a-select-option v-for="topic in allTopics" :key="topic.id" :value="topic.id">
                {{ topic.title }}
              </a-select-option>
            </a-select>
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
            <li
              v-for="task in board.governance?.tasks || []"
              :id="`task-${task.id}`"
              :key="task.id"
              :class="{ 'selected-governance-item': route.query.task_id === task.id }"
            >
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
                <a-select :value="selectedExecutorFor(task)" style="width: 120px"
                  :disabled="!configuredExecutors(task).length" placeholder="未启用"
                  @change="(value) => executorSelection[task.id] = value"
                  ><a-select-option v-for="key in configuredExecutors(task)" :key="key" :value="key">{{ key === 'codex' ? 'Codex' : 'OpenCode' }}</a-select-option></a-select
                >
                <a-button size="small" :disabled="busy || !configuredExecutors(task).length" @click="delegateTask(task)"
                  >委派执行</a-button
                >
                <span v-if="!configuredExecutors(task).length" class="workbench-muted">请先在数字员工设置中启用执行器</span>
              </template>
              <ul v-if="taskDelegations(task.id).length" class="delegation-list">
                <li v-for="item in taskDelegations(task.id)" :key="item.operation_id">
                  {{ item.executor_key }} · {{ delegationStatusLabel(item) }}
                  <span v-if="item.error_code"> · {{ item.error_code }}</span>
                  <span v-if="item.remote_status === 'failed'"> · 执行会话失败</span>
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
                  <a-button v-if="item.session_id" type="link" size="small" @click="showSession(item)">查看执行详情</a-button>
                  <p v-if="sessionDetails[item.session_id]" class="delegation-detail">
                    会话 {{ item.session_id }} · {{ sessionDetails[item.session_id].status }}
                    <span v-if="sessionDetails[item.session_id].error_code"> · {{ sessionDetails[item.session_id].error_code }}</span>
                    <span v-if="sessionDetails[item.session_id].error_message"> · {{ sessionDetails[item.session_id].error_message }}</span>
                  </p>
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
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import { MessagesSquare } from '@lucide/vue'
import { codingSessionApi } from '@/apis/coding_session_api'
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
const topicComposerVisible = ref(false)
const topicDraftTitle = ref('')
const topicDraftSummary = ref('')
const selectedTopicId = ref('')
const topicComments = ref([])
const topicCommentsLoading = ref(false)
const topicCommentError = ref('')
const commentDraft = ref('')
const editingTopic = ref(false)
const editingTopicTitle = ref('')
const editingTopicSummary = ref('')
const decisionTitle = ref('')
const decisionConclusion = ref('')
const decisionRationale = ref('')
const decisionTopicId = ref(undefined)
const taskTitle = ref('')
const taskDescription = ref('')
const taskTopicId = ref(undefined)
const taskDecisionId = ref(undefined)
const taskAgentSlug = ref(undefined)
const executorSelection = ref({})
const sessionDetails = ref({})
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
let topicCommentSeq = 0
const pageTitle = computed(() =>
  board.value?.project?.name ? `${board.value.project.name} · 项目工作台` : '项目工作台'
)
const allTopics = computed(() => board.value.governance?.topics || [])
const selectedTopic = computed(() => allTopics.value.find((item) => item.id === selectedTopicId.value))
const topicTitleFor = (topicId) => allTopics.value.find((item) => item.id === topicId)?.title || ''
const decisionDetail = (decision) =>
  [decision.conclusion, decision.rationale && `---\n\n**决策理由**\n\n${decision.rationale}`]
    .filter(Boolean)
    .join('\n\n')
const taskDelegations = (taskId) =>
  delegations.value.filter((item) => item.governance_task_id === taskId)
const configuredExecutors = (task) => {
  const agent = agents.value.find((item) => item.slug === task.assignee_agent_slug)
  const coding = { ...(agent?.config_json?.coding || {}), ...(agent?.config_overrides?.coding || {}) }
  return Array.isArray(coding.executors)
    ? coding.executors.filter((key) => ['codex', 'opencode'].includes(key))
    : []
}
const selectedExecutorFor = (task) => {
  const enabled = configuredExecutors(task)
  return enabled.includes(executorSelection.value[task.id])
    ? executorSelection.value[task.id]
    : enabled[0]
}
const delegationStatusLabel = (item) => ({
  queued: '等待派发', dispatching: '派发中', dispatched: '已派发', reclaimed: '已回收',
  running: '执行中', completed: '已完成', failed: '失败', cancelled: '已取消'
})[item.remote_status || item.dispatch_state] || item.remote_status || item.dispatch_state
const terminalTurn = (status) =>
  ['completed', 'failed', 'cancelled', 'interrupted'].includes(status)
const archiveTimeLabel = (raw) => {
  const value = String(raw || '')
  if (!/^\d{8}T\d{12}Z$/.test(value)) return value
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}T${value.slice(9, 11)}:${value.slice(11, 13)}:${value.slice(13, 15)}.${value.slice(15, 18)}Z`
  return new Date(iso).toLocaleString('zh-CN')
}
const timestampLabel = (raw) => {
  if (!raw) return ''
  const date = new Date(raw)
  return Number.isNaN(date.getTime()) ? String(raw) : date.toLocaleString('zh-CN')
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

function setTopicRoute(topicId) {
  const query = { ...route.query }
  if (topicId) query.topic_id = topicId
  else delete query.topic_id
  delete query.task_id
  delete query.decision_id
  router.replace({
    name: 'ProjectInspectionBoardComp',
    params: { project_id: projectId.value },
    query,
    hash: route.hash
  })
}

function selectTopic(topic) {
  if (!canLeaveTopicEditor()) return
  selectedTopicId.value = topic.id
  editingTopic.value = false
  commentDraft.value = ''
  topicCommentError.value = ''
  setTopicRoute(topic.id)
}

function createDecisionFromTopic(topic) {
  if (!canLeaveTopicEditor()) return
  selectedTopicId.value = topic.id
  decisionTopicId.value = topic.id
  decisionTitle.value = topic.title
  decisionConclusion.value = ''
  decisionRationale.value = ''
  setTopicRoute(topic.id)
  nextTick(() => jumpTo('decision-entry'))
}

function canLeaveTopicEditor() {
  if (
    !editingTopic.value ||
    !selectedTopic.value ||
    (editingTopicTitle.value === selectedTopic.value.title &&
      editingTopicSummary.value === (selectedTopic.value.summary || ''))
  )
    return true
  topicCommentError.value = '当前提议有未保存的修改，请先保存或取消编辑。'
  return false
}

function beginEditTopic() {
  if (!selectedTopic.value || selectedTopic.value.status !== 'proposed') return
  editingTopicTitle.value = selectedTopic.value.title
  editingTopicSummary.value = selectedTopic.value.summary || ''
  editingTopic.value = true
}

async function loadTopicComments() {
  const project = projectId.value
  const topicId = selectedTopicId.value
  const seq = ++topicCommentSeq
  topicComments.value = []
  topicCommentError.value = ''
  if (!topicId || !project) {
    topicCommentsLoading.value = false
    return
  }
  topicCommentsLoading.value = true
  try {
    const comments = await api.listTopicComments(project, topicId)
    if (seq !== topicCommentSeq || projectId.value !== project || selectedTopicId.value !== topicId)
      return
    topicComments.value = comments
  } catch (error) {
    if (seq === topicCommentSeq && projectId.value === project && selectedTopicId.value === topicId)
      topicCommentError.value = describeBoardError(error)
  } finally {
    if (seq === topicCommentSeq && projectId.value === project && selectedTopicId.value === topicId)
      topicCommentsLoading.value = false
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
    const topics = boardResult.value.governance?.topics || []
    const requestedTopicId = String(route.query.topic_id || '')
    const nextTopic =
      topics.find((item) => item.id === requestedTopicId) ||
      topics.find((item) => item.id === selectedTopicId.value) ||
      [...topics].reverse().find((item) => item.status === 'proposed') ||
      [...topics].reverse()[0]
    selectedTopicId.value = nextTopic?.id || ''
    if (requestedTopicId && !topics.some((item) => item.id === requestedTopicId)) setTopicRoute('')
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
    blueprintActionError.value = '名称需以中文、英文小写或数字开头，可含点、下划线或短横线，且不超过 120 字'
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
const submitTopic = () =>
  act(async () => {
    const created = await api.createTopic(projectId.value, {
      title: topicDraftTitle.value,
      summary: topicDraftSummary.value
    })
    topicDraftTitle.value = ''
    topicDraftSummary.value = ''
    topicComposerVisible.value = false
    selectedTopicId.value = created.id
    setTopicRoute(created.id)
  })
const saveTopicEdit = () =>
  act(async () => {
    await api.updateTopic(projectId.value, selectedTopic.value.id, {
      title: editingTopicTitle.value,
      summary: editingTopicSummary.value
    })
    editingTopic.value = false
  })
const postTopicComment = () =>
  act(async () => {
    await api.createTopicComment(projectId.value, selectedTopic.value.id, commentDraft.value)
    commentDraft.value = ''
    await loadTopicComments()
  }, topicCommentError)
const reviewTopic = (topic, approve) =>
  act(() => api.reviewTopic(projectId.value, topic.id, approve))
const createDecision = () =>
  act(async () => {
    await api.createDecision(projectId.value, {
      title: decisionTitle.value,
      conclusion: decisionConclusion.value,
      rationale: decisionRationale.value,
      topic_id: decisionTopicId.value || null
    })
    decisionTitle.value = ''
    decisionConclusion.value = ''
    decisionRationale.value = ''
    decisionTopicId.value = undefined
  })
const createTask = () =>
  act(async () => {
    await api.createTask(projectId.value, {
      title: taskTitle.value,
      description: taskDescription.value,
      topic_id: taskTopicId.value || null,
      decision_id: taskDecisionId.value || null,
      assignee_agent_slug: taskAgentSlug.value || null
    })
    taskTitle.value = ''
    taskDescription.value = ''
    taskTopicId.value = undefined
  })
const reviewTask = (task, approve) => act(() => api.reviewTask(projectId.value, task.id, approve))
const delegateTask = (task) =>
  act(() => api.delegateTask(projectId.value, task.id, selectedExecutorFor(task)))
async function showSession(item) {
  try {
    const detail = await codingSessionApi.detail(item.session_id)
    sessionDetails.value = { ...sessionDetails.value, [item.session_id]: detail.session || detail }
  } catch (error) {
    actionError.value = describeBoardError(error)
  }
}
let delegationPoll = null
async function pollDelegations() {
  if (loading.value || busy.value || !delegations.value.some((item) =>
    item.dispatch_state !== 'reclaimed' && !terminalTurn(item.remote_status))) return
  const project = projectId.value
  try {
    const rows = await api.listDelegations(project)
    if (project === projectId.value) delegations.value = rows
  } catch {
    // 手动刷新仍可重试；轮询不覆盖页面上的其他错误。
  }
}
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
  selectedTopicId.value = ''
  topicComments.value = []
  topicCommentsLoading.value = false
  topicCommentSeq += 1
  topicCommentError.value = ''
  commentDraft.value = ''
  topicComposerVisible.value = false
  topicDraftTitle.value = ''
  topicDraftSummary.value = ''
  editingTopic.value = false
  editingTopicTitle.value = ''
  editingTopicSummary.value = ''
  decisionTitle.value = ''
  decisionConclusion.value = ''
  decisionRationale.value = ''
  decisionTopicId.value = undefined
  taskTopicId.value = undefined
  load()
})
watch(
  () => route.query.topic_id,
  (topicId) => {
    const requested = String(topicId || '')
    if (!requested || !allTopics.value.some((item) => item.id === requested)) return
    if (requested !== selectedTopicId.value && !canLeaveTopicEditor()) {
      setTopicRoute(selectedTopicId.value)
      return
    }
    selectedTopicId.value = requested
  }
)
watch(selectedTopicId, loadTopicComments)
watch(
  [loading, () => route.query.task_id, () => route.query.decision_id],
  async ([isLoading, taskId, decisionId]) => {
    if (isLoading) return
    const recordId = taskId ? `task-${taskId}` : decisionId ? `decision-${decisionId}` : ''
    if (!recordId) return
    await nextTick()
    jumpTo(recordId)
  },
  { immediate: true }
)
watch(
  [loading, () => route.hash],
  async ([isLoading, hash]) => {
    if (isLoading || !hash || !sectionLinks.some((item) => `#${item.id}` === hash)) return
    await nextTick()
    jumpTo(hash.slice(1))
  },
  { immediate: true }
)
onMounted(() => {
  load()
  delegationPoll = setInterval(pollDelegations, 10000)
})
onUnmounted(() => clearInterval(delegationPoll))
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
.topic-composer,
.decision-entry {
  display: grid;
  gap: 12px;
  padding: 18px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-25);
}
.composer-heading,
.topic-sidebar-heading,
.discussion-heading,
.topic-review-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.composer-heading h3,
.discussion-heading h4 {
  margin: 0;
  color: var(--gray-1000);
  font-size: 16px;
}
.composer-heading p,
.discussion-heading p,
.topic-review-actions p {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}
.topic-layout {
  display: grid;
  grid-template-columns: minmax(230px, 290px) minmax(0, 1fr);
  align-items: start;
  gap: 16px;
}
.topic-sidebar {
  display: grid;
  gap: 8px;
  min-width: 0;
}
.topic-sidebar-heading {
  justify-content: space-between;
  padding: 4px 2px;
  color: var(--gray-800);
}
.topic-sidebar-heading span,
.discussion-heading > span {
  color: var(--gray-500);
  font-size: 12px;
}
.topic-list-empty {
  padding: 12px;
}
.topic-list-card {
  display: grid;
  gap: 8px;
  padding: 9px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
}
.topic-list-card.active {
  border-color: var(--main-color);
  box-shadow: 0 0 0 2px var(--main-30);
}
.topic-select {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 7px;
  width: 100%;
  padding: 2px;
  border: 0;
  background: transparent;
  color: var(--gray-800);
  cursor: pointer;
  text-align: left;
}
.topic-select:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}
.topic-list-title {
  min-width: 0;
  color: var(--gray-1000);
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}
.topic-select :deep(.ant-tag) {
  margin: 0;
}
.topic-list-summary {
  grid-column: 1 / -1;
  display: -webkit-box;
  overflow: hidden;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.topic-detail,
.topic-detail-empty {
  min-width: 0;
  padding: 20px;
  border: 1px solid var(--gray-150);
  border-radius: 9px;
  background: var(--gray-0);
}
.topic-detail {
  display: grid;
  gap: 18px;
}
.topic-detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--gray-100);
}
.topic-detail-heading h3 {
  margin: 0 0 8px;
  color: var(--gray-1000);
  font-size: 20px;
  overflow-wrap: anywhere;
}
.topic-detail-heading .eyebrow {
  margin: 0 0 6px;
  color: var(--main-color);
  font-size: 11px;
}
.topic-proposal-body,
.discussion-post {
  min-width: 0;
  color: var(--gray-800);
  overflow-wrap: anywhere;
}
.topic-proposal-body :deep(.yk-markdown-preview),
.discussion-post :deep(.yk-markdown-preview) {
  line-height: 1.75;
}
.topic-editor {
  display: grid;
  gap: 12px;
}
.discussion-thread {
  display: grid;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid var(--gray-100);
}
.discussion-heading {
  align-items: flex-start;
}
.discussion-empty {
  margin: 0;
  padding: 18px;
  border-radius: 7px;
  background: var(--gray-25);
  color: var(--gray-500);
  text-align: center;
}
.discussion-post {
  padding: 14px 16px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
  background: var(--gray-25);
}
.discussion-post > header {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.discussion-post > header strong {
  color: var(--gray-900);
}
.discussion-post time {
  color: var(--gray-500);
  font-size: 12px;
}
.discussion-reply {
  display: grid;
  gap: 9px;
  padding-top: 8px;
}
.topic-review-actions {
  align-items: center;
  padding-top: 14px;
  border-top: 1px solid var(--gray-100);
}
.topic-review-actions strong {
  color: var(--gray-800);
}
.topic-review-note {
  margin: 0;
}
.topic-detail-empty {
  display: grid;
  justify-items: start;
  gap: 9px;
  color: var(--gray-500);
}
.topic-detail-empty strong {
  color: var(--gray-800);
}
.topic-detail-empty p {
  margin: 0;
}
.decision-entry {
  scroll-margin-top: 16px;
}
.decision-records {
  display: grid;
  gap: 10px;
  scroll-margin-top: 16px;
}
.decision-card {
  display: grid;
  gap: 8px;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-0);
  scroll-margin-top: 16px;
}
.decision-card > header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.decision-card > header strong {
  color: var(--gray-1000);
}
.decision-card > p {
  margin: 0;
}
.selected-governance-item {
  border-color: var(--main-color) !important;
  box-shadow: 0 0 0 2px var(--main-30);
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
  .topic-layout {
    grid-template-columns: 1fr;
  }
  .topic-sidebar {
    max-height: 360px;
    overflow-y: auto;
  }
  .topic-review-actions {
    align-items: flex-start;
    flex-direction: column;
  }
  .topic-detail,
  .topic-detail-empty {
    padding: 15px;
  }
}
</style>
