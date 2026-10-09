<template>
  <div class="work-task-page">
    <PageHeader :title="task?.title || '项目工作'" :loading="loading" show-border>
      <template #actions><a-button size="small" @click="returnToSource">{{ returnPath ? '返回来源' : '工作列表' }}</a-button><a-button size="small" @click="router.push({ name: 'ProjectWorkTasksView', params: { project_id: route.params.project_id } })">任务管理</a-button></template>
    </PageHeader>
    <main class="work-task-content">
      <a-spin v-if="loading && !task" class="work-task-state" />
      <a-alert v-else-if="error && !task" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <template v-else-if="task">
        <p v-if="loading" class="work-task-muted">正在刷新工作详情，输入仍保留。</p>
        <a-alert v-if="error" type="error" show-icon :message="error"><template #action><a-button @click="load">重试</a-button></template></a-alert>
        <a-alert v-if="actionError" type="error" show-icon :message="actionError" />
        <a-alert v-if="attachmentError" type="error" show-icon :message="attachmentError" />
        <div class="work-task-heading">
          <span class="work-task-number">{{ task.number }}</span>
          <h1>{{ task.title }}</h1>
          <span class="work-task-status">{{ statusLabel(task.status) }}</span>
        </div>
        <section class="work-task-section">
          <WorkResultsPanel :project-id="String(route.params.project_id)" :task="task" :executions="executions" :completion-busy="saving" :anchor="route.hash" @select-result="id => router.replace({ hash: `#work-result-${id}` })" @complete-task="selectedStatus = 'done'; updateStatus()" @download-attachment="downloadResultAttachment" @refresh="load" @complete="completeWithGitCheck" />
        </section>
        <details class="work-management" :open="route.hash.startsWith('#work-execution-')"><summary>来源、执行历史与工作管理</summary>
        <p v-if="task.parent_id" class="work-task-parent">
          父任务：<RouterLink :to="{ name: 'ProjectWorkTaskView', params: { project_id: route.params.project_id, task_id: task.parent_id } }">查看父任务</RouterLink>
        </p>

        <section class="work-task-section">
          <h2>工作来源 <a-button size="small" @click="editSource">调整来源</a-button></h2>
          <p v-if="!task.source?.topic && !task.source?.decision" class="work-task-muted">独立工作，未关联议题或决策。</p>
          <p v-for="suggestion in task.suggestions || []" :key="suggestion.id">工作建议：<RouterLink class="work-task-link" :to="inspectionLink({ task_id: suggestion.id })">{{ suggestion.title }}</RouterLink>
            <RouterLink v-if="suggestion.decision_id" class="work-task-link" :to="inspectionLink({ decision_id: suggestion.decision_id })">建议来源决策</RouterLink>
          </p>
          <p v-if="task.source?.topic">来源议题：<RouterLink class="work-task-link" :to="inspectionLink({ topic_id: task.topic_id })">{{ task.source.topic.title }}</RouterLink>
            {{ task.source.topic.archived ? ' · 已归档' : '' }}</p>
          <template v-if="task.source?.decision">
            <p>来源决策：<RouterLink class="work-task-link" :to="inspectionLink({ decision_id: task.source_decision_id })">{{ task.source.decision.title }}</RouterLink>
              · 版本 {{ task.source_decision_revision }} · {{ governanceStatusLabel(task.source.decision.status) }}</p>
            <a-alert v-if="['superseded', 'revoked'].includes(task.source.decision.status)" type="warning" show-icon
              message="来源决策已被替代或撤销，请重新核对工作依据" description="当前来源及执行保持原样，可维持历史依据或手动调整后续来源。" />
            <a-alert v-if="task.source.decision.requires_review" type="warning" show-icon message="补充决策原依据已变化，需复核；工作继续保持当前来源。" />
            <details><summary>选定版本的批准原文</summary>
              <MarkdownPreview :content="task.source.decision.snapshot?.conclusion || ''" />
              <MarkdownPreview :content="task.source.decision.snapshot?.rationale || ''" />
            </details>
          </template>
          <form v-if="sourceEditing" @submit.prevent="saveSource">
            <WorkSourceFields v-model:topic-id="sourceTopic" v-model:decision-id="sourceDecision"
              v-model:review-confirmed="sourceReviewed" :topics="sourceTopics" :decisions="sourceDecisions" :disabled="saving" />
            <p class="work-task-muted">调整只影响后续分配；当前尝试、旧输入和工作编号保留。</p>
            <p v-if="sourceError" class="work-task-error" role="alert">{{ sourceError }}</p>
            <a-button @click="sourceEditing = false">取消</a-button>
            <a-button html-type="submit" type="primary" :loading="saving">保存来源</a-button>
          </form>
        </section>

        <section class="work-task-section">
          <h2>任务管理</h2>
          <div class="work-task-controls">
            <label for="task-status">状态</label>
            <a-select id="task-status" v-model:value="selectedStatus" :disabled="saving" style="min-width: 160px">
              <a-select-option v-for="item in statuses" :key="item.value" :value="item.value">{{ item.label }}</a-select-option>
            </a-select>
            <a-button :loading="saving" :disabled="selectedStatus === task.status" @click="updateStatus">保存状态</a-button>
          </div>
          <div class="work-task-controls">
            <label for="task-owner">第一负责人</label>
            <a-select id="task-owner" v-model:value="selectedOwner" allow-clear :disabled="saving" placeholder="暂不指定" style="min-width: 220px">
              <a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{ agent.name || agent.slug }}</a-select-option>
            </a-select>
            <a-button :loading="saving" :disabled="(selectedOwner || null) === task.primary_owner_agent_slug" @click="updateOwner">保存负责人</a-button>
          </div>
          <div class="work-task-controls">
            <label for="task-start">计划时间</label>
            <input id="task-start" v-model="selectedStart" type="date" :disabled="saving" aria-label="计划开始日期" />
            <span>至</span>
            <input v-model="selectedDue" type="date" :disabled="saving" aria-label="计划结束日期" />
            <a-button :loading="saving" :disabled="selectedStart === (task.start_date || '') && selectedDue === (task.due_date || '')" @click="updateSchedule">保存计划</a-button>
          </div>
        </section>

        <section class="work-task-section">
          <h2>网页引用</h2>
          <p v-if="!task.references?.length" class="work-task-muted">暂无引用</p>
          <ul v-else>
            <li v-for="reference in task.references" :key="reference.id">
              <a :href="reference.url" target="_blank" rel="noopener noreferrer">{{ reference.title }}</a>
              <a-button type="link" :loading="saving" @click="removeReference(reference.id)">移除</a-button>
            </li>
          </ul>
          <div class="work-task-controls">
            <a-input v-model:value="referenceTitle" :disabled="saving" maxlength="512" placeholder="引用标题" />
            <a-input v-model:value="referenceUrl" :disabled="saving" maxlength="2048" placeholder="https://example.com" />
            <a-button :loading="saving" :disabled="!referenceTitle.trim() || !referenceUrl.trim()" @click="addReference">添加引用</a-button>
          </div>
          <p v-if="referenceError" class="work-task-error" role="alert">{{ referenceError }}</p>
        </section>

        <section class="work-task-section">
          <h2>文件附件</h2>
          <p v-if="!task.attachments?.length" class="work-task-muted">暂无附件</p>
          <ul v-else>
            <li v-for="attachment in task.attachments" :key="attachment.id">
              <button type="button" class="work-task-link" :disabled="saving" @click="downloadAttachment(attachment)">
                {{ attachment.file_name }}
              </button>
              <span class="work-task-muted">{{ formatSize(attachment.file_size) }} · {{ formatTime(attachment.created_at) }}</span>
              <a-button type="link" :loading="saving" @click="removeAttachment(attachment.id)">移除</a-button>
            </li>
          </ul>
          <div class="work-task-controls">
            <input ref="attachmentInput" type="file" :disabled="saving" @change="uploadAttachment" />
          </div>
          <p v-if="attachmentError" class="work-task-error" role="alert">{{ attachmentError }}</p>
        </section>

        <section class="work-task-section">
          <h2>系统规则巡检</h2>
          <div class="work-task-controls">
            <label for="task-inspection">启用巡检</label>
            <a-switch id="task-inspection" v-model:checked="inspectionEnabled" :disabled="saving" />
            <label for="task-interval">周期（分钟）</label>
            <a-input-number id="task-interval" v-model:value="inspectionInterval" :min="1" :max="10080" :disabled="saving" />
            <a-button :loading="saving" @click="saveInspection">保存巡检</a-button>
          </div>
          <p class="work-task-muted">启用后系统按周期规则只读核查任务状态，第一负责人作为跟进标识；发现异常时写入任务评论并通知创建人。进行中但没有待接受或运行中执行尝试会被判为异常。</p>
          <p v-if="inspectionError" class="work-task-error" role="alert">{{ inspectionError }}</p>
          <p v-if="!task.inspection_runs?.length" class="work-task-muted">暂无巡检记录</p>
          <ul v-else>
            <li v-for="run in task.inspection_runs" :key="run.id">
              <span>{{ formatTime(run.inspected_at || run.created_at) }} · {{ run.finding ? '异常' : '正常' }}</span>
              <span class="work-task-muted">{{ run.summary || '未发现异常' }}</span>
            </li>
          </ul>
        </section>

        <section class="work-task-section">
          <h2>任务知识库</h2>
          <div class="work-task-controls">
          <a-select v-model:value="selectedKnowledges" mode="multiple" placeholder="默认不选择知识库" :disabled="saving" style="min-width: 220px">
            <a-select-option v-for="item in task.knowledge_candidates || []" :key="item.kb_id" :value="item.kb_id">{{ item.name }}</a-select-option>
          </a-select>
          <a-button :loading="saving" @click="saveKnowledges">保存知识库</a-button>
          <p class="work-task-muted">候选来自项目已关联且当前可访问的知识库；只在执行此任务时加入选择，运行时重新检查权限。</p>
          </div>
        </section>

        <section v-if="task.parent_id" class="work-task-section">
          <h2>子任务 Git 工作区</h2>
          <div class="work-task-controls">
          <a-select v-model:value="selectedGitWorkspaceMode" :disabled="saving || executions.length > 0" style="min-width: 280px">
              <a-select-option value="inherit">共用父任务工作区</a-select-option>
              <a-select-option value="isolated">从父任务已提交 HEAD 创建独立工作区</a-select-option>
            </a-select>
            <a-button :loading="saving" :disabled="executions.length > 0 || selectedGitWorkspaceMode === (task.git_workspace_mode || 'inherit')" @click="updateGitWorkspaceMode">保存工作区方式</a-button>
          </div>
          <p class="work-task-muted">执行前选择；已有执行记录后保持工作区身份，避免历史成果被重新归属。</p>
        </section>
        <p v-if="!task.acceptance_criteria" class="work-task-muted">尚未填写验收条件，派发前请核对工作要求。</p>
        <WorkContextDrawer ref="contextDrawer" :project-id="String(route.params.project_id)" :task="task" @context="executionContext = $event" />
        <WorkDelegationsPanel :completion-busy="saving" :anchor="route.hash" :context="executionContext" @history="(id) => contextDrawer?.showHistory('delegation', id)" :project-id="String(route.params.project_id)" :task-id="task.id" :title="task.title" :description="task.description" :agents="agents" :ended="['done', 'cancelled'].includes(task.status)" />
        <section class="work-task-section">
          <h2>智能体执行 <a-button size="small" type="link" @click="load">刷新状态</a-button></h2>
          <div class="work-task-controls">
            <a-select v-model:value="selectedExecutor" :disabled="saving || ['done', 'cancelled'].includes(task.status)" placeholder="选择执行智能体" style="min-width: 220px">
              <a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{ agent.name || agent.slug }}</a-select-option>
            </a-select>
            <a-button :loading="saving" :disabled="!selectedExecutor || executions.some((item) => activeExecutionStatuses.includes(item.status)) || ['done', 'cancelled'].includes(task.status)" @click="assignExecution">分配任务</a-button>
          </div>
          <p class="work-task-muted">分配后若显示“待接受”，可在此处接单启动；开启工作台自动接受后，新分配会自动进入队列。</p>
          <p class="work-task-muted">“重新执行”只针对失败或已取消的尝试，会创建新的执行意图并绑定新的 Run，旧尝试保留可追踪。</p>
          <p v-if="!executions.length" class="work-task-muted">暂无执行记录</p>
          <ul v-else>
            <li v-for="item in executions" :id="`work-execution-${item.id}`" :key="item.id">
              <span class="work-execution-main">
                {{ agentName(item.agent_slug) }} · {{ executionStatusLabel(item.status) }} · {{ formatTime(item.created_at) }}
                <span v-if="item.source_decision_id"> · 当次来源：<RouterLink class="work-task-link" :to="inspectionLink({ decision_id: item.source_decision_id })">决策版本 {{ item.source_decision_revision }}</RouterLink></span>
                <span v-if="item.source_topic_id"> · <RouterLink class="work-task-link" :to="inspectionLink({ topic_id: item.source_topic_id })">当次议题</RouterLink></span>
                <span v-if="item.current_run_id" class="work-execution-run"> · Run {{ item.current_run_id }}</span>
                <span v-if="item.error_message" class="work-task-error"> · {{ item.error_message }}</span>
              </span>
              <span class="work-execution-actions">
                <a-button type="link" @click="contextDrawer?.showHistory('execution', item.id)">查看当次资料</a-button>
                <RouterLink v-if="item.thread_id && ['submitted', 'interrupted'].includes(item.status)" :to="{ name: 'AgentCompWithThreadId', params: { thread_id: item.thread_id } }">进入执行会话</RouterLink>
                <RouterLink :to="{ name: 'ProjectAgentWorkbenchView', params: { project_id: route.params.project_id, agent_slug: item.agent_slug } }">查看工作台</RouterLink>
                <a-button v-if="retryableStatuses.includes(item.status)" type="link" :loading="saving" @click="retryExecution(item)">重新执行</a-button>
                <a-button v-if="item.status === 'pending_acceptance'" type="link" :loading="saving" @click="acceptExecution(item)">接受并执行</a-button>
                <a-button v-if="['pending_acceptance', 'queued'].includes(item.status)" type="link" :loading="saving" @click="cancelExecution(item)">撤回分配</a-button>
              </span>
            </li>
          </ul>
        </section>

        <section class="work-task-section">
          <h2>问题单</h2>
          <div class="work-task-controls">
            <a-input v-model:value="issueTitle" maxlength="512" :disabled="saving" placeholder="新问题单标题" />
            <a-button :loading="saving" :disabled="!issueTitle.trim()" @click="createIssue">新建 Issue</a-button>
          </div>
          <a-textarea v-model:value="issueDescription" :rows="2" :disabled="saving" placeholder="问题详情（可选）" />
          <p v-if="!task.issues?.length" class="work-task-muted">暂无问题单</p>
          <ul v-else>
            <li v-for="issue in task.issues" :key="issue.id">
              <a-button type="link" @click="openIssue(issue.id)">{{ issue.number }} · {{ issue.title }}</a-button>
              <span class="work-task-muted">{{ issueStatusLabel(issue.status) }}</span>
            </li>
          </ul>
          <div v-if="selectedIssue" class="work-task-issue">
            <h3>{{ selectedIssue.number }} · {{ selectedIssue.title }}</h3>
            <p v-if="selectedIssue.description" class="work-task-description">{{ selectedIssue.description }}</p>
            <div class="work-task-controls">
              <a-select v-model:value="issueStatus" :disabled="saving" style="min-width: 150px">
                <a-select-option value="open">待处理</a-select-option>
                <a-select-option value="resolved">已解决</a-select-option>
                <a-select-option value="closed">已关闭</a-select-option>
              </a-select>
              <a-button :loading="saving" :disabled="issueStatus === selectedIssue.status" @click="updateIssue">保存 Issue 状态</a-button>
            </div>
            <p v-if="!selectedIssue.comments?.length" class="work-task-muted">暂无 Issue 评论</p>
            <ul v-else>
              <li v-for="comment in selectedIssue.comments" :key="comment.id" class="work-task-comment">
                <strong>{{ comment.author_name }}</strong>
                <span class="work-task-muted">{{ formatTime(comment.created_at) }}</span>
                <p>{{ comment.content }}</p>
              </li>
            </ul>
            <a-textarea v-model:value="issueDraft" :rows="2" :disabled="saving" placeholder="记录问题结论" />
            <a-button :loading="saving" :disabled="!issueDraft.trim()" @click="addIssueComment">发表 Issue 评论</a-button>
          </div>
        </section>

        <section class="work-task-section">
          <h2>任务讨论</h2>
          <p v-if="!task.comments?.length" class="work-task-muted">暂无评论</p>
          <ul v-else>
            <li v-for="comment in task.comments" :key="comment.id" class="work-task-comment">
              <strong>{{ comment.author_name }}</strong>
              <span class="work-task-muted">{{ formatTime(comment.created_at) }}</span>
              <p>{{ comment.content }}</p>
            </li>
          </ul>
          <a-textarea v-model:value="draft" :rows="3" :disabled="saving" placeholder="记录结论或进展" :maxlength="100000" />
          <a-button type="primary" :loading="saving" :disabled="!draft.trim()" @click="addComment">发表评论</a-button>
          <p v-if="actionError" class="work-task-error" role="alert">{{ actionError }}</p>
        </section>
        </details>
      </template>
    </main>
    <a-modal v-model:open="gitCompletionOpen" title="任务仍有 Git 成果需要处理" :footer="null">
      <p>是否先提交、推送、发起合并或释放占用？标记任务完成会保留当前成果。</p>
      <a-alert v-for="failure in gitCompletion?.errors || []" :key="failure" type="warning" :message="failure" show-icon />
      <p v-if="gitCompletion?.scope_key && gitCompletion.scope_key !== `task:${route.params.task_id}`">共享父任务工作区时，此处包含共享工作区的成果。</p>
      <div v-for="resource in gitCompletion?.resources || []" :key="resource.worktree_id">
        <p><strong>{{ resource.alias }}</strong> · {{ resource.branch }}</p>
        <a-tag v-for="issue in resource.issues" :key="issue">{{ gitIssueLabel(issue) }}</a-tag>
        <a-alert v-for="failure in resource.errors" :key="failure" type="warning" :message="failure" show-icon />
      </div>
      <a-button @click="gitCompletionOpen = false; gitResourceSettingsOpen = true">先处理成果</a-button>
      <a-button :loading="saving" @click="confirmTaskCompletion">保留成果并标记完成</a-button>
    </a-modal>
    <ProjectGitSettingsModal v-model:open="gitResourceSettingsOpen" :project="{ id: String(route.params.project_id), name: '任务资源' }" />
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import ProjectGitSettingsModal from '@/components/ProjectGitSettingsModal.vue'
import WorkDelegationsPanel from '@/components/project/WorkDelegationsPanel.vue'
import WorkContextDrawer from '@/components/project/WorkContextDrawer.vue'
import { useUserStore } from '@/stores/user'
import { clearReviewScope } from '@/utils/resultReviewDrafts'
import { projectWorkApi } from '@/apis/project_work_api'
import WorkSourceFields from '@/components/project/WorkSourceFields.vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { governanceStatusLabel } from '@/utils/governanceBoard'
import { governanceBoardApi } from '@/apis/governance_board_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import WorkResultsPanel from '@/components/project/WorkResultsPanel.vue'
import { projectWorkExecutionApi } from '@/apis/project_work_execution_api'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const returnPath = computed(() => {
  const current = route.fullPath
  const back = router.options.history.state.back
  if (typeof back !== 'string' || !back.startsWith('/') || back.startsWith('//')) return ''
  const target = router.resolve(back)
  const allowed = ['ProjectDashboardComp', 'ProjectWorkTasksView', 'ProjectInspectionBoardComp', 'ProjectAgentWorkbenchView', 'InboxView', 'InspectionBoardComp']
  return target.fullPath !== current && allowed.includes(target.name) && (!target.params.project_id || target.params.project_id === route.params.project_id) ? back : ''
})
function returnToSource() {
  if (returnPath.value) router.back()
  else router.push({ name: 'ProjectWorkTasksView', params: { project_id: route.params.project_id } })
}

const contextDrawer = ref(null), executionContext = ref(null)
const task = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const actionError = ref('')
const draft = ref('')
const selectedGitWorkspaceMode = ref('inherit')
const agents = ref([])
const executions = ref([])
const pendingCompletion = ref(null)
const selectedExecutor = ref(undefined)
const selectedStatus = ref('todo')
const selectedKnowledges = ref([])
const gitCompletionOpen = ref(false)
const gitResourceSettingsOpen = ref(false)
const gitCompletion = ref(null)
const gitIssueLabel = (issue) => ({ uncommitted: '未提交', unpushed: '远端与本地提交不一致', unmerged: '当前提交尚未确认合并', unreleased: '尚未释放占用', unarchived: '工作树尚未回收', not_ready: '工作区未就绪' })[issue] || issue
const selectedOwner = ref(undefined)
const selectedStart = ref('')
const selectedDue = ref('')
const issueTitle = ref('')
const issueDescription = ref('')
const selectedIssue = ref(null)
const issueStatus = ref('open')
const issueDraft = ref('')
const referenceTitle = ref('')
const referenceUrl = ref('')
const referenceError = ref('')
const attachmentInput = ref(null)
const attachmentError = ref('')
const inspectionEnabled = ref(false)
const inspectionInterval = ref(60)
const inspectionError = ref('')
const sourceEditing = ref(false)
const sourceTopic = ref(undefined)
const sourceDecision = ref(undefined)
const sourceReviewed = ref(false)
const sourceTopics = ref([])
const sourceDecisions = ref([])
const sourceError = ref('')
let sourceExpected = null
const inspectionLink = (query) => ({ name: 'ProjectInspectionBoardComp', params: { project_id: route.params.project_id }, query })
async function editSource() {
  const project = route.params.project_id, id = task.value.id
  sourceError.value = ''
  try {
    const [topics, decisions] = await Promise.all([projectWorkApi.listTopics(project), governanceBoardApi.listDecisions(project)])
    if (project !== route.params.project_id || id !== task.value?.id) return
    sourceTopics.value = topics
    sourceDecisions.value = decisions
    sourceTopic.value = task.value.topic_id || undefined
    sourceDecision.value = task.value.source_decision_id || undefined
    sourceReviewed.value = false
    sourceExpected = { expected_topic_id: task.value.topic_id, expected_decision_id: task.value.source_decision_id,
      expected_decision_revision: task.value.source_decision_revision }
    sourceEditing.value = true
  } catch (cause) { actionError.value = cause?.message || '来源加载失败' }
}
async function saveSource() {
  if (saving.value) return
  const project = route.params.project_id, id = task.value.id
  saving.value = true
  sourceError.value = ''
  try {
    await projectWorkApi.updateSource(project, id, { ...sourceExpected, topic_id: sourceTopic.value || null,
      source_decision_id: sourceDecision.value || null, review_confirmed: sourceReviewed.value })
    if (project !== route.params.project_id || id !== task.value?.id) return
    sourceEditing.value = false
    await load()
  } catch (cause) { if (project === route.params.project_id && id === task.value?.id) sourceError.value = cause?.message || '来源保存失败，选择已保留' }
  finally { saving.value = false }
}
let loadVersion = 0
let issueVersion = 0
const statuses = [
  { value: 'todo', label: '待办' },
  { value: 'in_progress', label: '进行中' },
  { value: 'blocked', label: '受阻' },
  { value: 'done', label: '已完成' },
  { value: 'cancelled', label: '已取消' }
]
const statusLabel = (status) => statuses.find((item) => item.value === status)?.label || status
const activeExecutionStatuses = ['pending_acceptance', 'queued', 'dispatching', 'submitted', 'interrupted']
const retryableStatuses = ['failed', 'cancelled']
const executionStatusLabel = (status) => ({
  pending_acceptance: '待接受', queued: '排队中', dispatching: '派发中', submitted: '执行中',
  interrupted: '等待答复', completed: '已完成', failed: '失败', cancelled: '已取消'
})[status] || status
const issueStatusLabel = (status) => ({ open: '待处理', resolved: '已解决', closed: '已关闭' })[status] || status
const agentName = (slug) => agents.value.find((agent) => agent.slug === slug)?.name || slug
const formatTime = (value) => (value ? new Date(value).toLocaleString('zh-CN') : '')

async function load() {
  const version = ++loadVersion
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  loading.value = true
  error.value = ''
  try {
    const [result, bindings, history] = await Promise.all([
      projectWorkApi.getTask(projectId, taskId),
      projectAgentApi.list(projectId),
      projectWorkExecutionApi.listForTask(projectId, taskId)
    ])
    if (version !== loadVersion) return
    const sameTask = task.value?.id === result.id
    const statusWasSaved = selectedStatus.value === task.value?.status
    const ownerWasSaved = (selectedOwner.value || null) === task.value?.primary_owner_agent_slug
    const gitWorkspaceWasSaved = selectedGitWorkspaceMode.value === (task.value?.git_workspace_mode || 'inherit')
    const scheduleWasSaved = selectedStart.value === (task.value?.start_date || '') && selectedDue.value === (task.value?.due_date || '')
    const inspectionWasSaved =
      inspectionEnabled.value === (task.value?.inspection_enabled ?? false) &&
      inspectionInterval.value === (task.value?.inspection_interval_minutes ?? null)
    if (!sameTask || JSON.stringify(selectedKnowledges.value) === JSON.stringify(task.value?.knowledge_ids || [])) selectedKnowledges.value = result.knowledge_ids || []
    if (!sameTask) sourceEditing.value = false
    task.value = result
    agents.value = bindings.agents || []
    executions.value = history
    if (!sameTask || statusWasSaved) selectedStatus.value = result.status
    if (!sameTask || gitWorkspaceWasSaved) selectedGitWorkspaceMode.value = result.git_workspace_mode || 'inherit'
    if (!sameTask || ownerWasSaved) selectedOwner.value = result.primary_owner_agent_slug || undefined
    if (!sameTask || scheduleWasSaved) {
      selectedStart.value = result.start_date || ''
      selectedDue.value = result.due_date || ''
    }
    if (!sameTask || inspectionWasSaved) {
      inspectionEnabled.value = result.inspection_enabled ?? false
      inspectionInterval.value = result.inspection_interval_minutes ?? 60
    }
    if (selectedIssue.value && !result.issues.some((item) => item.id === selectedIssue.value.id)) selectedIssue.value = null
  } catch (cause) {
    if (version === loadVersion) {
      error.value = cause?.message || '任务加载失败'
      if ([401, 403, 404].includes(cause?.status)) { clearReviewScope(user.uid, projectId, taskId); task.value = null; executions.value = [] }
    }
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function runAction(action, fallback, errorTarget = actionError) {
  if (saving.value) return
  const version = loadVersion
  saving.value = true
  actionError.value = ''
  errorTarget.value = ''
  try {
    await action()
    if (version === loadVersion) await load()
  } catch (cause) {
    if (version === loadVersion) {
      errorTarget.value = cause?.message || fallback
      if ([401, 403, 404].includes(cause?.status)) { clearReviewScope(user.uid, route.params.project_id, route.params.task_id); task.value = null; error.value = errorTarget.value }
    }
  } finally {
    saving.value = false
  }
}

function completeWithGitCheck(action) {
  const version = loadVersion
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(async () => {
    let result
    try {
      result = await projectWorkApi.getGitOutcomes(projectId, taskId)
    } catch (failure) {
      result = { requires_attention: true, resources: [], errors: [failure?.message || '无法确认 Git 成果，请检查后明确选择保留成果'] }
    }
    if (version !== loadVersion || projectId !== route.params.project_id || taskId !== route.params.task_id) return
    if (result.requires_attention) {
      pendingCompletion.value = action
      gitCompletion.value = result
      gitCompletionOpen.value = true
      return
    }
    await action(false)
  }, '完成操作失败')
}

function updateStatus() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const status = selectedStatus.value
  if (status === 'done') return completeWithGitCheck((confirmed) => projectWorkApi.updateTask(projectId, taskId, { status, git_outcomes_confirmed: confirmed }))
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, { status }), '状态保存失败')
}

function confirmTaskCompletion() {
  const action = pendingCompletion.value
  if (!action) return
  return runAction(async () => {
    await action(true)
    gitCompletionOpen.value = false
    pendingCompletion.value = null
  }, '完成操作失败')
}

function saveKnowledges() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const knowledgeIds = [...selectedKnowledges.value]
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, { knowledge_ids: knowledgeIds }), '知识库保存失败')
}

function updateGitWorkspaceMode() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const mode = selectedGitWorkspaceMode.value
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, { git_workspace_mode: mode }), '工作区方式保存失败')
}

function updateOwner() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const primaryOwner = selectedOwner.value || null
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, { primary_owner_agent_slug: primaryOwner }), '负责人保存失败')
}

function updateSchedule() {
  if (selectedStart.value && selectedDue.value && selectedStart.value > selectedDue.value) {
    actionError.value = '计划结束日期不能早于开始日期'
    return
  }
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, {
    start_date: selectedStart.value || null,
    due_date: selectedDue.value || null
  }), '计划保存失败')
}

async function addReference() {
  if (saving.value) return
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const title = referenceTitle.value.trim()
  const url = referenceUrl.value.trim()
  const version = loadVersion
  saving.value = true
  referenceError.value = ''
  try {
    await projectWorkApi.addReference(projectId, taskId, { title, url })
    if (version !== loadVersion) return
    if (projectId === route.params.project_id && taskId === route.params.task_id) {
      referenceTitle.value = ''
      referenceUrl.value = ''
    }
    await load()
  } catch (cause) {
    if (version === loadVersion) referenceError.value = cause?.message || '引用添加失败'
  } finally {
    saving.value = false
  }
}

function removeReference(referenceId) {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(
    () => projectWorkApi.removeReference(projectId, taskId, referenceId),
    '引用移除失败',
    referenceError
  )
}

function formatSize(bytes) {
  const size = Number(bytes) || 0
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

async function uploadAttachment(event) {
  const input = event.target
  const file = input.files?.[0]
  input.value = ''
  if (!file || saving.value) return
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const version = loadVersion
  saving.value = true
  attachmentError.value = ''
  try {
    await projectWorkApi.uploadAttachment(projectId, taskId, file)
    if (version === loadVersion) await load()
  } catch (cause) {
    if (version === loadVersion) attachmentError.value = cause?.message || '附件上传失败'
  } finally {
    saving.value = false
  }
}

function downloadResultAttachment(id) {
  const attachment = task.value?.attachments?.find(item => item.id === id)
  if (attachment) return downloadAttachment(attachment)
  attachmentError.value = '该附件不在当前工作中，请刷新核对交付引用'
}

async function downloadAttachment(attachment) {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const version = loadVersion, owner = user.uid
  attachmentError.value = ''
  try {
    const response = await projectWorkApi.downloadAttachment(projectId, taskId, attachment.id)
    const blob = await response.blob()
    if (version !== loadVersion || owner !== user.uid) return
    const disposition = response.headers.get('Content-Disposition') || response.headers.get('content-disposition')
    const match = disposition?.match(/filename\*=UTF-8''([^;]+)/i)
    const fileName = match ? decodeURIComponent(match[1]) : attachment.file_name
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = fileName
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    window.URL.revokeObjectURL(url)
  } catch (cause) {
    if (version === loadVersion && owner === user.uid) attachmentError.value = cause?.message || '附件下载失败'
  }
}

function removeAttachment(attachmentId) {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(
    () => projectWorkApi.removeAttachment(projectId, taskId, attachmentId),
    '附件移除失败',
    attachmentError
  )
}

function saveInspection() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const payload = {
    inspection_enabled: inspectionEnabled.value,
    inspection_interval_minutes: inspectionInterval.value || null
  }
  return runAction(
    () => projectWorkApi.updateTask(projectId, taskId, payload),
    '巡检配置保存失败',
    inspectionError
  )
}

function assignExecution() {
  if (executionContext.value && !executionContext.value.expected_fingerprint) { actionError.value = '资料选择已变化，请重新预览后执行'; return }
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const agentSlug = selectedExecutor.value
  return runAction(() => projectWorkExecutionApi.assign(projectId, taskId, agentSlug, executionContext.value), '任务分配失败')
}

function acceptExecution(item) {
  const projectId = route.params.project_id
  return runAction(
    () => projectWorkExecutionApi.accept(projectId, item.agent_slug, item.id),
    '任务接受失败'
  )
}

function cancelExecution(item) {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(() => projectWorkExecutionApi.cancel(projectId, taskId, item.id), '撤回分配失败')
}

function retryExecution(item) {
  if (executionContext.value && !executionContext.value.expected_fingerprint) { actionError.value = '资料选择已变化，请重新预览后执行'; return }
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(() => projectWorkExecutionApi.assign(projectId, taskId, item.agent_slug, executionContext.value), '重新执行失败')
}

function createIssue() {
  const title = issueTitle.value.trim()
  const description = issueDescription.value.trim() || null
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(async () => {
    await projectWorkApi.createIssue(projectId, taskId, { title, description })
    if (projectId === route.params.project_id && taskId === route.params.task_id) {
      issueTitle.value = ''
      issueDescription.value = ''
    }
  }, 'Issue 创建失败')
}

async function openIssue(issueId, { clearDraft = true } = {}) {
  const version = ++issueVersion
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  actionError.value = ''
  try {
    const result = await projectWorkApi.getIssue(projectId, taskId, issueId)
    if (version !== issueVersion || projectId !== route.params.project_id || taskId !== route.params.task_id) return
    selectedIssue.value = result
    issueStatus.value = result.status
    if (clearDraft) issueDraft.value = ''
  } catch (cause) {
    if (version === issueVersion) actionError.value = cause?.message || 'Issue 加载失败'
  }
}

function updateIssue() {
  const issueId = selectedIssue.value.id
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(async () => {
    await projectWorkApi.updateIssue(projectId, taskId, issueId, issueStatus.value)
    if (projectId === route.params.project_id && taskId === route.params.task_id && selectedIssue.value?.id === issueId) await openIssue(issueId, { clearDraft: false })
  }, 'Issue 状态保存失败')
}

function addIssueComment() {
  const issueId = selectedIssue.value.id
  const content = issueDraft.value.trim()
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(async () => {
    await projectWorkApi.addIssueComment(projectId, taskId, issueId, content)
    if (projectId === route.params.project_id && taskId === route.params.task_id && selectedIssue.value?.id === issueId) await openIssue(issueId)
  }, 'Issue 评论发送失败')
}

async function addComment() {
  if (saving.value) return
  const content = draft.value.trim()
  if (!content) return
  const version = loadVersion
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  saving.value = true
  actionError.value = ''
  try {
    await projectWorkApi.addComment(projectId, taskId, content)
    if (version !== loadVersion) return
    draft.value = ''
    await load()
  } catch (cause) {
    if (version === loadVersion) actionError.value = cause?.message || '评论发送失败'
  } finally {
    saving.value = false
  }
}

watch([() => route.params.project_id, () => route.params.task_id, () => user.uid], () => {
  task.value = null
  executionContext.value = null;
  gitCompletionOpen.value = false
  gitResourceSettingsOpen.value = false
  gitCompletion.value = null
  if (!route.params.project_id || !route.params.task_id) {
    ++loadVersion
    ++issueVersion
    loading.value = false
    return
  }
  ++issueVersion
  selectedIssue.value = null
  issueTitle.value = ''
  issueDescription.value = ''
  issueDraft.value = ''
  referenceTitle.value = ''
  referenceUrl.value = ''
  referenceError.value = ''
  attachmentError.value = ''
  inspectionError.value = ''
  selectedExecutor.value = undefined
  selectedStart.value = ''
  selectedDue.value = ''
  executions.value = []
  pendingCompletion.value = null
  draft.value = ''
  actionError.value = ''
  load()
}, { immediate: true })
/** 在异步详情渲染后定位业务结果或当次执行，避免只落到页首。 */
watch([() => route.hash, task, executions, loading], async () => {
  if (loading.value || !route.hash.startsWith('#work-')) return
  await nextTick()
  if (typeof document !== 'undefined') document.getElementById(route.hash.slice(1))?.scrollIntoView?.({ block: 'center' })
}, { flush: 'post' })
</script>

<style scoped lang="less">
.work-task-page :deep(.page-header) { position: sticky; top: 0; z-index: 2; background: var(--gray-0); }
.work-task-content { max-width: 1080px; margin: 0 auto; padding: 24px; }
.work-management > summary { padding: 14px 0; font-weight: 600; cursor: pointer; }
.work-task-state { display: block; margin: 56px auto; }
.work-task-number { color: var(--main-color); font-size: 13px; }
.work-task-heading h1 { margin: 6px 0; color: var(--gray-900); font-size: 24px; }
.work-task-status { color: var(--gray-600); }
.work-task-description { margin: 24px 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--gray-800); }
.work-task-parent { color: var(--gray-600); }
.work-task-section { border-top: 1px solid var(--gray-150); padding: 20px 0; }
.work-task-section h2 { font-size: 17px; color: var(--gray-900); }
.work-task-section h3 { font-size: 15px; color: var(--gray-900); }
.work-task-controls { display: flex; align-items: center; gap: 12px; margin: 12px 0; }
.work-task-controls label { min-width: 72px; }
.work-task-controls input[type='date'] { border: 1px solid var(--gray-200); border-radius: 6px; padding: 5px 8px; color: var(--gray-900); background: var(--gray-0, #fff); }
.work-task-issue { padding: 16px; background: var(--gray-25); border: 1px solid var(--gray-150); border-radius: 8px; }
.work-task-section ul { list-style: none; margin: 0 0 18px; padding: 0; }
.work-task-section li { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--gray-100); }
.work-task-muted { color: var(--gray-500); }
.work-task-link { border: none; background: none; padding: 0; color: var(--main-color); cursor: pointer; text-align: left; overflow-wrap: anywhere; }
.work-task-link:disabled { color: var(--gray-400); cursor: default; }
.work-execution-main { min-width: 0; overflow-wrap: anywhere; }.work-execution-run { color: var(--gray-500); font-size: 12px; }
.work-execution-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.work-task-comment { display: block !important; }
.work-task-comment p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.work-task-section :deep(textarea) { margin-bottom: 12px; }
.work-task-error { margin-top: 12px; color: var(--color-error-700); }
@media (max-width: 640px) { .work-task-controls { flex-wrap: wrap; } }
</style>
