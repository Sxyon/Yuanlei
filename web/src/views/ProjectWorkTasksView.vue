<template>
  <div class="work-tasks-page">
    <PageHeader title="项目工作任务" :loading="loading" show-border>
      <template #actions>
        <a-button size="small" @click="router.push({ name: 'ProjectInspectionBoardComp', params: { project_id: projectId } })">项目工作台</a-button>
        <a-button size="small" :disabled="loading || saving || savingCode" @click="load">刷新</a-button>
      </template>
    </PageHeader>
    <main class="work-tasks-content">
      <a-alert v-if="error" type="error" show-icon :message="error" class="work-tasks-alert">
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <a-spin v-else-if="loading" class="work-tasks-loading" />
      <template v-else>
        <section class="work-tasks-section">
          <h2>新建任务</h2>
          <p class="work-tasks-help">首次创建前先设置项目缩写。缩写一旦保存便固定，用于后续任务编号。</p>
          <div class="work-tasks-row">
            <label for="work-code">项目缩写</label>
            <a-input id="work-code" v-model:value="projectCode" maxlength="12" :disabled="codeSaved || savingCode" placeholder="例如 YL" class="work-tasks-code" />
    <a-button :loading="savingCode" :disabled="!projectCode.trim() || codeSaved" @click="saveCode">{{ codeSaved ? '已固化' : '保存缩写' }}</a-button>
          </div>
          <div class="work-tasks-fields">
            <label for="work-title">任务标题</label>
            <a-input id="work-title" v-model:value="title" maxlength="512" :disabled="saving" placeholder="输入任务标题" />
            <label for="work-description">任务详情</label>
            <a-textarea id="work-description" v-model:value="description" :rows="3" :disabled="saving" placeholder="目标、范围和验收条件" />
            <label for="work-parent">父任务</label>
            <a-select id="work-parent" v-model:value="parentId" allow-clear :disabled="saving" placeholder="可选：作为子任务" style="width: 100%">
              <a-select-option v-for="item in tasks" :key="item.id" :value="item.id">{{ item.number }} · {{ item.title }}</a-select-option>
            </a-select>
            <label for="work-owner">第一负责人</label>
            <a-select id="work-owner" v-model:value="ownerSlug" allow-clear :disabled="saving" placeholder="可选：项目数字员工" style="width: 100%">
              <a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{ agent.name || agent.slug }}</a-select-option>
            </a-select>
          </div>
          <a-button type="primary" :loading="saving" :disabled="!title.trim()" @click="createTask">创建任务</a-button>
          <p v-if="actionError" class="work-tasks-error" role="alert">{{ actionError }}</p>
        </section>
        <section class="work-tasks-section">
          <div class="work-tasks-heading">
            <h2>任务列表</h2>
            <a-select v-model:value="filter" aria-label="筛选任务状态" class="work-tasks-filter">
              <a-select-option value="all">全部</a-select-option>
              <a-select-option v-for="status in statuses" :key="status.value" :value="status.value">{{ status.label }}</a-select-option>
            </a-select>
          </div>
          <a-empty v-if="!visibleTasks.length" description="暂无符合条件的任务" />
          <ul v-else class="work-tasks-list">
            <li v-for="item in visibleTasks" :key="item.id">
              <RouterLink :to="{ name: 'ProjectWorkTaskView', params: { project_id: projectId, task_id: item.id } }">
                <span class="work-tasks-number">{{ item.number }}</span>
                <strong>{{ item.title }}</strong>
              </RouterLink>
              <span class="work-tasks-meta">
                {{ statusLabel(item.status) }}<template v-if="item.primary_owner_agent_slug"> · {{ item.primary_owner_agent_slug }}</template>
                <RouterLink v-if="item.parent_id" :to="{ name: 'ProjectWorkTaskView', params: { project_id: projectId, task_id: item.parent_id } }">· 父任务 {{ parentNumber(item.parent_id) }}</RouterLink>
              </span>
            </li>
          </ul>
        </section>
      </template>
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import { projectWorkApi } from '@/apis/project_work_api'
import { projectAgentApi } from '@/apis/project_agent_api'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => String(route.params.project_id || ''))
const tasks = ref([])
const agents = ref([])
const loading = ref(false)
const saving = ref(false)
const savingCode = ref(false)
const error = ref('')
const actionError = ref('')
const projectCode = ref('')
const codeSaved = ref(false)
const title = ref('')
const description = ref('')
const parentId = ref(undefined)
const ownerSlug = ref(undefined)
const filter = ref('all')
const statuses = [
  { value: 'todo', label: '待办' },
  { value: 'in_progress', label: '进行中' },
  { value: 'blocked', label: '受阻' },
  { value: 'done', label: '已完成' },
  { value: 'cancelled', label: '已取消' }
]
const statusLabel = (status) => statuses.find((item) => item.value === status)?.label || status
const parentNumber = (parentId) => tasks.value.find((item) => item.id === parentId)?.number || '查看'
const visibleTasks = computed(() => tasks.value.filter((item) => filter.value === 'all' || item.status === filter.value))
let loadVersion = 0
let codeWriteVersion = 0

async function load() {
  const version = ++loadVersion
  const codeVersion = codeWriteVersion
  const project = projectId.value
  loading.value = true
  error.value = ''
  try {
    const [items, bindings, code] = await Promise.all([
      projectWorkApi.listTasks(project),
      projectAgentApi.list(project),
      projectWorkApi.getCode(project)
    ])
    if (version !== loadVersion || project !== projectId.value) return
    tasks.value = items
    agents.value = bindings.agents || []
    if (codeVersion === codeWriteVersion) {
      projectCode.value = code.code || ''
      codeSaved.value = Boolean(code.code)
    }
  } catch (cause) {
    if (version === loadVersion) error.value = cause?.message || '任务加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function saveCode() {
  const project = projectId.value
  ++codeWriteVersion
  savingCode.value = true
  actionError.value = ''
  try {
    const result = await projectWorkApi.configureCode(project, projectCode.value)
    if (project === projectId.value) {
      projectCode.value = result.code
      codeSaved.value = true
    }
  } catch (cause) {
    if (project === projectId.value) actionError.value = cause?.message || '项目缩写保存失败'
  } finally {
    savingCode.value = false
  }
}

async function createTask() {
  const project = projectId.value
  saving.value = true
  actionError.value = ''
  try {
    const created = await projectWorkApi.createTask(project, {
      title: title.value.trim(),
      description: description.value.trim() || null,
      parent_id: parentId.value || null,
      primary_owner_agent_slug: ownerSlug.value || null
    })
    if (project !== projectId.value) return
    title.value = ''
    description.value = ''
    parentId.value = undefined
    ownerSlug.value = undefined
    await router.push({ name: 'ProjectWorkTaskView', params: { project_id: project, task_id: created.id } })
  } catch (cause) {
    if (project === projectId.value) actionError.value = cause?.message || '任务创建失败，请检查项目缩写是否已保存'
  } finally {
    saving.value = false
  }
}

watch(projectId, () => {
  tasks.value = []
  agents.value = []
  projectCode.value = ''
  codeSaved.value = false
  title.value = ''
  description.value = ''
  parentId.value = undefined
  ownerSlug.value = undefined
  filter.value = 'all'
  actionError.value = ''
  load()
}, { immediate: true })
</script>

<style scoped lang="less">
.work-tasks-content { max-width: 960px; margin: 0 auto; padding: 24px; }
.work-tasks-loading { display: block; margin: 56px auto; }
.work-tasks-alert { margin-bottom: 16px; }
.work-tasks-section { padding: 20px 0; border-bottom: 1px solid var(--gray-150); }
.work-tasks-section h2 { margin: 0 0 12px; color: var(--gray-900); font-size: 18px; }
.work-tasks-help, .work-tasks-meta { color: var(--gray-600); }
.work-tasks-row, .work-tasks-heading { display: flex; align-items: center; gap: 12px; margin-bottom: 18px; }
.work-tasks-row label { white-space: nowrap; }
.work-tasks-code { max-width: 180px; }
.work-tasks-fields { display: grid; grid-template-columns: 92px minmax(0, 1fr); align-items: center; gap: 12px; margin-bottom: 18px; }
.work-tasks-filter { width: 160px; margin-left: auto; }
.work-tasks-list { list-style: none; margin: 0; padding: 0; }
.work-tasks-list li { display: flex; justify-content: space-between; gap: 16px; padding: 12px 0; border-top: 1px solid var(--gray-100); }
.work-tasks-list a { display: flex; flex-wrap: wrap; gap: 12px; color: var(--gray-900); }
.work-tasks-number { color: var(--main-color); }
.work-tasks-error { margin-top: 12px; color: var(--color-error-700); }
@media (max-width: 640px) {
  .work-tasks-fields { grid-template-columns: 1fr; gap: 8px; }
  .work-tasks-list li { flex-direction: column; gap: 4px; }
}
</style>
