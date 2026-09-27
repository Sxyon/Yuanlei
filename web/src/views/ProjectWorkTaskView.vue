<template>
  <div class="work-task-page">
    <PageHeader title="项目任务" :loading="loading" show-border>
      <template #actions><a-button size="small" @click="router.push('/inbox')">返回收件箱</a-button></template>
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

        <section class="work-task-section">
          <h2>问题单</h2>
          <p v-if="!task.issues?.length" class="work-task-muted">暂无问题单</p>
          <ul v-else>
            <li v-for="issue in task.issues" :key="issue.id">
              <span>{{ issue.number }} · {{ issue.title }}</span>
              <span class="work-task-muted">{{ issue.status }}</span>
            </li>
          </ul>
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
          <a-textarea v-model:value="draft" :rows="3" placeholder="记录结论或进展" :maxlength="100000" />
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

const route = useRoute()
const router = useRouter()
const task = ref(null)
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const actionError = ref('')
const draft = ref('')
let loadVersion = 0
const statusLabel = (status) => ({ todo: '待办', in_progress: '进行中', blocked: '受阻', done: '已完成', cancelled: '已取消' })[status] || status
const formatTime = (value) => (value ? new Date(value).toLocaleString('zh-CN') : '')

async function load() {
  const version = ++loadVersion
  const projectId = route.params.project_id
  const taskId = route.params.task_id
  loading.value = true
  error.value = ''
  try {
    const result = await projectWorkApi.getTask(projectId, taskId)
    if (version !== loadVersion) return
    task.value = result
  } catch (cause) {
    if (version === loadVersion) error.value = cause?.message || '任务加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function addComment() {
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
.work-task-section { border-top: 1px solid var(--gray-150); padding: 20px 0; }
.work-task-section h2 { font-size: 17px; color: var(--gray-900); }
.work-task-section ul { list-style: none; margin: 0 0 18px; padding: 0; }
.work-task-section li { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--gray-100); }
.work-task-muted { color: var(--gray-500); }
.work-task-comment { display: block !important; }
.work-task-comment p { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.work-task-section :deep(textarea) { margin-bottom: 12px; }
.work-task-error { margin-top: 12px; color: var(--color-error-700); }
</style>
