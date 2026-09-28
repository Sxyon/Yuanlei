<template>
  <div class="work-task-page">
    <PageHeader title="项目任务" :loading="loading" show-border>
      <template #actions><a-button size="small" @click="router.push({ name: 'ProjectWorkTasksView', params: { project_id: route.params.project_id } })">任务列表</a-button></template>
    </PageHeader>
    <main class="work-task-content">
      <a-spin v-if="loading" class="work-task-state" />
      <a-alert v-else-if="error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <template v-else-if="task">
        <div class="work-task-heading">
          <span class="work-task-number">{{ task.number }}</span>
          <h1>{{ task.title }}</h1>
          <span class="work-task-status">{{ statusLabel(task.status) }}</span>
        </div>
        <p class="work-task-description">{{ task.description || '暂无详情' }}</p>
        <p v-if="task.parent_id" class="work-task-parent">
          父任务：<RouterLink :to="{ name: 'ProjectWorkTaskView', params: { project_id: route.params.project_id, task_id: task.parent_id } }">查看父任务</RouterLink>
        </p>

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
          <h2>智能体执行</h2>
          <div class="work-task-controls">
            <a-select v-model:value="selectedExecutor" :disabled="saving || ['done', 'cancelled'].includes(task.status)" placeholder="选择执行智能体" style="min-width: 220px">
              <a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{ agent.name || agent.slug }}</a-select-option>
            </a-select>
            <a-button :loading="saving" :disabled="!selectedExecutor || executions.some((item) => activeExecutionStatuses.includes(item.status)) || ['done', 'cancelled'].includes(task.status)" @click="assignExecution">分配任务</a-button>
          </div>
          <p v-if="!executions.length" class="work-task-muted">暂无执行记录</p>
          <ul v-else>
            <li v-for="item in executions" :key="item.id">
              <span>{{ item.agent_slug }} · {{ executionStatusLabel(item.status) }} · {{ formatTime(item.created_at) }}</span>
              <span>
                <RouterLink :to="{ name: 'ProjectAgentWorkbenchView', params: { project_id: route.params.project_id, agent_slug: item.agent_slug } }">查看工作台</RouterLink>
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
              <span class="work-task-muted">{{ issue.status }}</span>
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
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import { projectWorkApi } from '@/apis/project_work_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import { projectWorkExecutionApi } from '@/apis/project_work_execution_api'

const route = useRoute()
const router = useRouter()
const task = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const actionError = ref('')
const draft = ref('')
const agents = ref([])
const executions = ref([])
const selectedExecutor = ref(undefined)
const selectedStatus = ref('todo')
const selectedOwner = ref(undefined)
const issueTitle = ref('')
const issueDescription = ref('')
const selectedIssue = ref(null)
const issueStatus = ref('open')
const issueDraft = ref('')
const referenceTitle = ref('')
const referenceUrl = ref('')
const referenceError = ref('')
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
const executionStatusLabel = (status) => ({
  pending_acceptance: '待接受', queued: '排队中', dispatching: '派发中', submitted: '执行中',
  interrupted: '等待答复', completed: '已完成', failed: '失败', cancelled: '已取消'
})[status] || status
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
    task.value = result
    agents.value = bindings.agents || []
    executions.value = history
    if (!sameTask || statusWasSaved) selectedStatus.value = result.status
    if (!sameTask || ownerWasSaved) selectedOwner.value = result.primary_owner_agent_slug || undefined
    if (selectedIssue.value && !result.issues.some((item) => item.id === selectedIssue.value.id)) selectedIssue.value = null
  } catch (cause) {
    if (version === loadVersion) error.value = cause?.message || '任务加载失败'
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
    if (version === loadVersion) errorTarget.value = cause?.message || fallback
  } finally {
    saving.value = false
  }
}

function updateStatus() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const status = selectedStatus.value
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, { status }), '状态保存失败')
}

function updateOwner() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const primaryOwner = selectedOwner.value || null
  return runAction(() => projectWorkApi.updateTask(projectId, taskId, { primary_owner_agent_slug: primaryOwner }), '负责人保存失败')
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

function assignExecution() {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  const agentSlug = selectedExecutor.value
  return runAction(() => projectWorkExecutionApi.assign(projectId, taskId, agentSlug), '任务分配失败')
}

function cancelExecution(item) {
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  return runAction(() => projectWorkExecutionApi.cancel(projectId, taskId, item.id), '撤回分配失败')
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

watch(() => [route.params.project_id, route.params.task_id], () => {
  ++issueVersion
  selectedIssue.value = null
  issueTitle.value = ''
  issueDescription.value = ''
  issueDraft.value = ''
  referenceTitle.value = ''
  referenceUrl.value = ''
  referenceError.value = ''
  selectedExecutor.value = undefined
  executions.value = []
  draft.value = ''
  actionError.value = ''
  load()
}, { immediate: true })
</script>

<style scoped lang="less">
.work-task-content { max-width: 920px; margin: 0 auto; padding: 24px; }
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
.work-task-issue { padding: 16px; background: var(--gray-25); border: 1px solid var(--gray-150); border-radius: 8px; }
.work-task-section ul { list-style: none; margin: 0 0 18px; padding: 0; }
.work-task-section li { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--gray-100); }
.work-task-muted { color: var(--gray-500); }
.work-task-comment { display: block !important; }
.work-task-comment p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.work-task-section :deep(textarea) { margin-bottom: 12px; }
.work-task-error { margin-top: 12px; color: var(--color-error-700); }
@media (max-width: 640px) { .work-task-controls { flex-wrap: wrap; } }
</style>
