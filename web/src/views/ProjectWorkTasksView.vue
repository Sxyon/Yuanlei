<template>
  <div class="tasks-page">
    <PageHeader title="项目工作任务" :loading="loading" show-border>
      <template #actions>
        <a-button size="small" @click="router.push({ name: 'ProjectInspectionBoardComp', params: { project_id: projectId } })">项目工作台</a-button>
        <a-button size="small" :disabled="loading" @click="load">刷新</a-button>
      </template>
    </PageHeader>
    <main class="tasks-content">
      <a-alert v-if="error" type="error" show-icon :message="error" class="tasks-alert">
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <a-spin v-else-if="loading" class="tasks-loading" />
      <template v-else>
        <header class="tasks-hero">
          <div>
            <p class="tasks-eyebrow">PROJECT TASKS <span v-if="codeSaved">· {{ projectCode }}</span></p>
            <h1>任务管理</h1>
            <p>按状态推进工作，在时间轴上安排计划，并查看每次智能体执行。</p>
          </div>
          <a-button type="primary" size="large" @click="openCreate">新建任务</a-button>
        </header>
        <div class="tasks-summary" aria-label="任务概况">
          <div><strong>{{ tasks.length }}</strong><span>全部任务</span></div>
          <div><strong>{{ countStatus('in_progress') }}</strong><span>进行中</span></div>
          <div><strong>{{ countStatus('blocked') }}</strong><span>受阻</span></div>
          <div><strong>{{ countStatus('done') }}</strong><span>已完成</span></div>
        </div>
        <section class="tasks-panel">
          <div class="tasks-toolbar">
            <div class="tasks-tabs" role="tablist" aria-label="任务视图">
              <button v-for="option in views" :key="option.value" type="button" role="tab"
                :aria-selected="view === option.value" :class="{ active: view === option.value }" @click="view = option.value">
                {{ option.label }}
              </button>
            </div>
            <div class="tasks-filters">
              <a-input v-model:value="search" allow-clear placeholder="搜索编号或标题" aria-label="搜索任务" class="tasks-search" />
              <a-select v-if="view !== 'board'" v-model:value="filter" aria-label="筛选任务状态" class="tasks-filter">
                <a-select-option value="all">全部状态</a-select-option>
                <a-select-option v-for="status in statuses" :key="status.value" :value="status.value">{{ status.label }}</a-select-option>
              </a-select>
            </div>
          </div>
          <div v-if="!tasks.length && view === 'board'" class="tasks-empty">
            <div class="tasks-empty-icon">✓</div>
            <h2>从第一个任务开始</h2>
            <p>记录工作目标，设置负责人和计划，再交给数字员工执行。</p>
            <a-button type="primary" @click="openCreate">新建任务</a-button>
          </div>
          <template v-else-if="view === 'board'">
            <div class="tasks-board">
              <section v-for="status in statuses" :key="status.value" class="tasks-column" :class="`status-${status.value}`">
                <header><span class="status-dot" /><h2>{{ status.label }}</h2><span class="column-count">{{ matchingTasks(status.value).length }}</span></header>
                <div class="column-body">
                  <div v-if="!matchingTasks(status.value).length" class="column-empty">暂无任务</div>
                  <article v-for="item in matchingTasks(status.value)" :key="item.id" class="task-card">
                    <RouterLink :to="taskRoute(item)" class="task-number">{{ item.number }}</RouterLink>
                    <RouterLink :to="taskRoute(item)" class="task-title">{{ item.title }}</RouterLink>
                    <p v-if="item.description" class="task-description">{{ item.description }}</p>
                    <div class="task-card-footer">
                      <span>{{ ownerName(item) }}</span>
                      <span v-if="item.due_date" :class="{ overdue: isOverdue(item) }">{{ item.due_date }}</span>
                    </div>
                    <a-select :value="item.status" size="small" :disabled="updatingId === item.id" aria-label="更改任务状态"
                      class="task-status-select" @change="(value) => changeStatus(item, value)">
                      <a-select-option v-for="next in statuses" :key="next.value" :value="next.value">{{ next.label }}</a-select-option>
                    </a-select>
                  </article>
                </div>
              </section>
            </div>
          </template>
          <template v-else-if="view === 'list'">
            <div v-if="!visibleTasks.length" class="view-empty">没有符合筛选条件的任务</div>
            <div v-else class="tasks-table-scroll">
              <table class="tasks-table">
                <thead><tr><th>编号 / 任务</th><th>状态</th><th>第一负责人</th><th>计划时间</th><th>更新时间</th></tr></thead>
                <tbody>
                  <tr v-for="item in visibleTasks" :key="item.id">
                    <td><RouterLink :to="taskRoute(item)" class="table-title"><small>{{ item.number }}</small><strong>{{ item.title }}</strong></RouterLink></td>
                    <td><span class="status-pill" :class="`status-${item.status}`">{{ statusLabel(item.status) }}</span></td>
                    <td>{{ ownerName(item) }}</td>
                    <td>{{ planLabel(item) }}</td>
                    <td>{{ formatTime(item.updated_at) }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </template>
          <template v-else>
            <div class="gantt-controls">
              <div><strong>计划时间轴</strong><p>点击“设置计划”安排任务起止日期</p></div>
              <label>查看月份 <input v-model="ganttMonth" type="month" aria-label="查看月份" /></label>
            </div>
            <div v-if="!visibleTasks.length" class="view-empty">没有符合筛选条件的任务</div>
            <div v-else class="gantt-scroll">
              <div class="gantt-grid" :style="{ '--days': monthDays.length }">
                <div class="gantt-head-name">任务</div>
                <div class="gantt-days"><span v-for="day in monthDays" :key="day.iso" :class="{ weekend: day.weekend, today: day.iso === today }">{{ day.day }}</span></div>
                <template v-for="item in visibleTasks" :key="item.id">
                  <div class="gantt-task"><RouterLink :to="taskRoute(item)"><small>{{ item.number }}</small>{{ item.title }}</RouterLink>
                    <button type="button" @click="openSchedule(item)">{{ item.start_date && item.due_date ? '调整计划' : '设置计划' }}</button>
                  </div>
                  <div class="gantt-track">
                    <span v-for="day in monthDays" :key="day.iso" :class="{ weekend: day.weekend, today: day.iso === today }" />
                    <div v-if="barFor(item)" class="gantt-bar" :class="`status-${item.status}`" :style="barFor(item)" :title="`${item.start_date} → ${item.due_date}`" />
                    <span v-else class="gantt-unplanned">{{ item.start_date && item.due_date ? '本月无计划' : '未安排' }}</span>
                  </div>
                </template>
              </div>
            </div>
          </template>
        </section>
        <p v-if="actionError" class="tasks-error" role="alert">{{ actionError }}</p>
      </template>
    </main>

    <a-modal v-model:open="createOpen" title="新建项目任务" :footer="null" :width="620" :body-style="{ maxHeight: 'calc(100vh - 190px)', overflowY: 'auto' }" :destroy-on-close="false">
      <div class="task-form">
        <div v-if="!codeSaved" class="code-setup">
          <strong>先设置项目编号缩写</strong>
          <p>首次创建时保存，之后所有任务沿用此缩写。项目内编号会自动递增。</p>
          <a-input v-model:value="projectCode" maxlength="12" placeholder="例如 YL" aria-label="项目编号缩写" />
        </div>
        <label><span class="field-title">任务标题 <em>*</em></span><a-input v-model:value="title" maxlength="512" placeholder="例如：完成季度客户访谈" /></label>
        <label>任务详情<a-textarea v-model:value="description" :rows="4" placeholder="写明目标、交付物和验收条件" /></label>
        <div class="form-pair">
          <label>计划开始 <input v-model="startDate" type="date" /></label>
          <label>计划结束 <input v-model="dueDate" type="date" /></label>
        </div>
        <div class="form-pair">
          <label>父任务<a-select v-model:value="parentId" allow-clear placeholder="可选：作为子任务"><a-select-option v-for="item in tasks" :key="item.id" :value="item.id">{{ item.number }} · {{ item.title }}</a-select-option></a-select></label>
          <label>第一负责人<a-select v-model:value="ownerSlug" allow-clear placeholder="可选：项目数字员工"><a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{ agent.name || agent.slug }}</a-select-option></a-select></label>
        </div>
        <p v-if="formError" class="tasks-error" role="alert">{{ formError }}</p>
        <div class="form-actions"><a-button @click="createOpen = false">取消</a-button><a-button type="primary" :loading="saving" :disabled="!title.trim() || (!codeSaved && !projectCode.trim())" @click="createTask">创建任务</a-button></div>
      </div>
    </a-modal>
    <a-modal v-model:open="scheduleOpen" title="设置任务计划" :footer="null" :width="440">
      <div class="task-form">
        <p class="schedule-title">{{ scheduledTask?.number }} · {{ scheduledTask?.title }}</p>
        <div class="form-pair"><label>开始日期<input v-model="scheduleStart" type="date" /></label><label>结束日期<input v-model="scheduleDue" type="date" /></label></div>
        <p v-if="formError" class="tasks-error" role="alert">{{ formError }}</p>
        <div class="form-actions"><a-button @click="scheduleOpen = false">取消</a-button><a-button type="primary" :loading="saving" @click="saveSchedule">保存计划</a-button></div>
      </div>
    </a-modal>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
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
const updatingId = ref('')
const error = ref('')
const actionError = ref('')
const formError = ref('')
const projectCode = ref('')
const codeSaved = ref(false)
const createOpen = ref(false)
const scheduleOpen = ref(false)
const scheduledTask = ref(null)
const title = ref('')
const description = ref('')
const startDate = ref('')
const dueDate = ref('')
const parentId = ref(undefined)
const ownerSlug = ref(undefined)
const scheduleStart = ref('')
const scheduleDue = ref('')
const filter = ref('all')
const search = ref('')
const view = ref('board')
const localToday = () => {
  const date = new Date()
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
}
const today = ref(localToday())
const ganttMonth = ref(today.value.slice(0, 7))
const views = [{ value: 'board', label: '看板' }, { value: 'list', label: '列表' }, { value: 'gantt', label: '甘特图' }]
const statuses = [
  { value: 'todo', label: '待办' }, { value: 'in_progress', label: '进行中' },
  { value: 'blocked', label: '受阻' }, { value: 'done', label: '已完成' }, { value: 'cancelled', label: '已取消' }
]
const statusLabel = (status) => statuses.find((item) => item.value === status)?.label || status
const ownerName = (item) => agents.value.find((agent) => agent.slug === item.primary_owner_agent_slug)?.name || item.primary_owner_agent_slug || '未指定'
const formatTime = (value) => value ? new Date(value).toLocaleDateString('zh-CN') : '—'
const planLabel = (item) => item.start_date && item.due_date ? `${item.start_date} → ${item.due_date}` : item.due_date || item.start_date || '未安排'
const isOverdue = (item) => item.due_date < today.value && !['done', 'cancelled'].includes(item.status)
const taskRoute = (item) => ({ name: 'ProjectWorkTaskView', params: { project_id: projectId.value, task_id: item.id } })
const countStatus = (status) => tasks.value.filter((item) => item.status === status).length
const matchesSearch = (item) => `${item.number} ${item.title}`.toLowerCase().includes(search.value.trim().toLowerCase())
const visibleTasks = computed(() => tasks.value.filter((item) => matchesSearch(item) && (filter.value === 'all' || item.status === filter.value)))
const matchingTasks = (status) => tasks.value.filter((item) => item.status === status && matchesSearch(item))
const monthDays = computed(() => {
  const [year, month] = ganttMonth.value.split('-').map(Number)
  if (!year || !month) return []
  return Array.from({ length: new Date(Date.UTC(year, month, 0)).getUTCDate() }, (_, index) => {
    const date = new Date(Date.UTC(year, month - 1, index + 1))
    return { iso: date.toISOString().slice(0, 10), day: index + 1, weekend: [0, 6].includes(date.getUTCDay()) }
  })
})
const barFor = (item) => {
  if (!item.start_date || !item.due_date || !monthDays.value.length) return null
  const first = monthDays.value[0].iso
  const last = monthDays.value.at(-1).iso
  if (item.due_date < first || item.start_date > last) return null
  const start = Math.max(0, monthDays.value.findIndex((day) => day.iso >= item.start_date))
  const end = monthDays.value.findIndex((day) => day.iso >= item.due_date)
  const lastIndex = end === -1 ? monthDays.value.length - 1 : end
  return { left: `${start / monthDays.value.length * 100}%`, width: `${(lastIndex - start + 1) / monthDays.value.length * 100}%` }
}
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
      projectWorkApi.listTasks(project), projectAgentApi.list(project), projectWorkApi.getCode(project)
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

function openCreate() {
  formError.value = ''
  createOpen.value = true
}

async function saveCode() {
  const project = projectId.value
  ++codeWriteVersion
  const code = await projectWorkApi.configureCode(project, projectCode.value.trim())
  if (project === projectId.value) {
    projectCode.value = code.code
    codeSaved.value = true
  }
}

async function createTask() {
  if (saving.value) return
  if (startDate.value && dueDate.value && startDate.value > dueDate.value) {
    formError.value = '计划结束日期不能早于开始日期'
    return
  }
  const project = projectId.value
  saving.value = true
  formError.value = ''
  try {
    if (!codeSaved.value) {
      await saveCode()
      if (project !== projectId.value) return
    }
    const created = await projectWorkApi.createTask(project, {
      title: title.value.trim(), description: description.value.trim() || null,
      parent_id: parentId.value || null, primary_owner_agent_slug: ownerSlug.value || null,
      start_date: startDate.value || null, due_date: dueDate.value || null
    })
    if (project !== projectId.value) return
    createOpen.value = false
    title.value = ''
    description.value = ''
    startDate.value = ''
    dueDate.value = ''
    parentId.value = undefined
    ownerSlug.value = undefined
    await load()
    await router.push(taskRoute(created))
  } catch (cause) {
    if (project === projectId.value) formError.value = cause?.message || '创建失败，请检查编号缩写和任务信息'
  } finally {
    saving.value = false
  }
}

async function changeStatus(item, status) {
  updatingId.value = item.id
  actionError.value = ''
  try {
    await projectWorkApi.updateTask(projectId.value, item.id, { status })
    await load()
  } catch (cause) {
    actionError.value = cause?.message || '状态更新失败'
  } finally {
    updatingId.value = ''
  }
}

function openSchedule(item) {
  scheduledTask.value = item
  scheduleStart.value = item.start_date || ''
  scheduleDue.value = item.due_date || ''
  formError.value = ''
  scheduleOpen.value = true
}

async function saveSchedule() {
  if (saving.value || !scheduledTask.value) return
  if (scheduleStart.value && scheduleDue.value && scheduleStart.value > scheduleDue.value) {
    formError.value = '计划结束日期不能早于开始日期'
    return
  }
  saving.value = true
  formError.value = ''
  try {
    await projectWorkApi.updateTask(projectId.value, scheduledTask.value.id, {
      start_date: scheduleStart.value || null, due_date: scheduleDue.value || null
    })
    scheduleOpen.value = false
    await load()
  } catch (cause) {
    formError.value = cause?.message || '计划保存失败'
  } finally {
    saving.value = false
  }
}

watch(projectId, () => {
  tasks.value = []
  agents.value = []
  projectCode.value = ''
  codeSaved.value = false
  createOpen.value = false
  scheduleOpen.value = false
  title.value = ''
  description.value = ''
  startDate.value = ''
  dueDate.value = ''
  parentId.value = undefined
  ownerSlug.value = undefined
  actionError.value = ''
  load()
}, { immediate: true })
let calendarTimer = null
onMounted(() => {
  calendarTimer = setInterval(() => {
    const next = localToday()
    if (next !== today.value) {
      if (ganttMonth.value === today.value.slice(0, 7)) ganttMonth.value = next.slice(0, 7)
      today.value = next
    }
  }, 60000)
})
onUnmounted(() => clearInterval(calendarTimer))
</script>

<style scoped lang="less">
.tasks-page { min-height: 100%; background: var(--gray-50, #f8fafc); }
.tasks-content { max-width: 1600px; margin: 0 auto; padding: 30px 34px 64px; }
.tasks-loading { display: block; margin: 64px auto; }
.tasks-alert { margin-bottom: 20px; }
.tasks-hero { display: flex; justify-content: space-between; align-items: center; gap: 20px; margin-bottom: 26px; }
.tasks-eyebrow { color: var(--main-color); font-size: 12px; font-weight: 700; letter-spacing: .1em; margin: 0 0 7px; }
.tasks-hero h1 { color: var(--gray-900); font-size: 28px; line-height: 1.2; margin: 0 0 8px; }
.tasks-hero p:last-child { color: var(--gray-600); margin: 0; }
.tasks-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 24px; }
.tasks-summary > div { background: var(--gray-0, #fff); border: 1px solid var(--gray-150); border-radius: 12px; padding: 17px 20px; display: flex; flex-direction: column; gap: 3px; }
.tasks-summary strong { font-size: 25px; color: var(--gray-900); line-height: 1.25; }
.tasks-summary span { color: var(--gray-600); font-size: 12px; }
.tasks-panel { background: var(--gray-0, #fff); border: 1px solid var(--gray-150); border-radius: 14px; overflow: hidden; min-height: 330px; }
.tasks-toolbar { padding: 16px 20px; display: flex; align-items: center; justify-content: space-between; gap: 20px; border-bottom: 1px solid var(--gray-150); }
.tasks-tabs { display: flex; gap: 4px; padding: 4px; border-radius: 9px; background: var(--gray-100); }
.tasks-tabs button { border: 0; border-radius: 7px; background: transparent; color: var(--gray-600); padding: 7px 15px; cursor: pointer; }
.tasks-tabs button.active { background: var(--gray-0, #fff); color: var(--gray-900); box-shadow: 0 1px 4px rgba(0,0,0,.08); font-weight: 600; }
.tasks-filters { display: flex; gap: 10px; }
.tasks-search { width: 220px; }.tasks-filter { width: 140px; }
.tasks-empty { text-align: center; padding: 62px 20px; }.tasks-empty-icon { margin: 0 auto 14px; width: 45px; height: 45px; border-radius: 14px; background: var(--gray-100); color: var(--main-color); font-size: 28px; }
.tasks-empty h2 { font-size: 19px; margin: 0 0 8px; }.tasks-empty p { color: var(--gray-600); margin-bottom: 20px; }
.tasks-board { display: grid; grid-template-columns: repeat(5, minmax(205px, 1fr)); overflow-x: auto; background: var(--gray-50, #f8fafc); }
.tasks-column { min-height: 360px; border-right: 1px solid var(--gray-150); }.tasks-column:last-child { border-right: 0; }
.tasks-column > header { display: flex; align-items: center; gap: 8px; padding: 17px 14px; border-bottom: 1px solid var(--gray-150); }
.tasks-column h2 { font-size: 13px; font-weight: 600; margin: 0; color: var(--gray-800); }.status-dot { width: 8px; height: 8px; background: var(--gray-400); border-radius: 50%; }
.status-in_progress .status-dot { background: #3b82f6; }.status-blocked .status-dot { background: #f59e0b; }.status-done .status-dot { background: #10b981; }.status-cancelled .status-dot { background: #94a3b8; }
.column-count { margin-left: auto; color: var(--gray-500); background: var(--gray-100); border-radius: 20px; padding: 1px 7px; font-size: 11px; }.column-body { padding: 10px; }
.column-empty { color: var(--gray-500); font-size: 12px; padding: 20px 8px; text-align: center; }
.task-card { padding: 14px; margin-bottom: 10px; border: 1px solid var(--gray-150); border-radius: 10px; background: var(--gray-0, #fff); box-shadow: 0 2px 7px rgba(15,23,42,.04); display: flex; flex-direction: column; gap: 9px; }
.task-card a { display: block; }.task-number { color: var(--main-color); font-size: 11px; font-weight: 700; }.task-title { color: var(--gray-900); font-weight: 600; line-height: 1.45; }
.task-description { color: var(--gray-600); font-size: 12px; line-height: 1.5; margin: 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.task-card-footer { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 5px; color: var(--gray-500); font-size: 11px; }.overdue { color: var(--color-error-700); }
.task-status-select { width: 100%; }.tasks-table-scroll, .gantt-scroll { overflow-x: auto; }.tasks-table { width: 100%; border-collapse: collapse; min-width: 780px; }
.tasks-table th { text-align: left; background: var(--gray-50, #f8fafc); color: var(--gray-600); font-size: 12px; font-weight: 600; padding: 13px 18px; }
.tasks-table td { padding: 15px 18px; border-top: 1px solid var(--gray-100); color: var(--gray-700); font-size: 13px; }.tasks-table tr:hover td { background: var(--gray-50, #f8fafc); }
.table-title { display: flex; flex-direction: column; color: var(--gray-900); gap: 3px; }.table-title small { color: var(--main-color); }.status-pill { display: inline-block; padding: 4px 9px; border-radius: 6px; background: var(--gray-100); }
.status-pill.status-in_progress { color: #2563eb; background: #eff6ff; }.status-pill.status-blocked { color: #b45309; background: #fffbeb; }.status-pill.status-done { color: #047857; background: #ecfdf5; }
.gantt-controls { display: flex; justify-content: space-between; gap: 15px; align-items: center; padding: 18px 20px; }.gantt-controls p { margin: 3px 0 0; color: var(--gray-500); font-size: 12px; }
.gantt-controls label { color: var(--gray-600); font-size: 12px; display: flex; align-items: center; gap: 8px; }.gantt-controls input, .task-form input[type=date] { border: 1px solid var(--gray-200); border-radius: 7px; background: var(--gray-0, #fff); color: var(--gray-900); padding: 6px 9px; }
.gantt-grid { display: grid; grid-template-columns: 235px minmax(680px, 1fr); min-width: 920px; }.gantt-head-name, .gantt-days { background: var(--gray-50, #f8fafc); color: var(--gray-600); border-top: 1px solid var(--gray-150); border-bottom: 1px solid var(--gray-150); }
.gantt-head-name { padding: 10px 15px; font-size: 12px; }.gantt-days, .gantt-track { display: grid; grid-template-columns: repeat(var(--days), minmax(0, 1fr)); }
.gantt-days span { text-align: center; font-size: 10px; padding: 11px 0; border-left: 1px solid var(--gray-100); }.gantt-days .weekend, .gantt-track .weekend { background: rgba(148,163,184,.08); }.gantt-days .today { color: var(--main-color); font-weight: 700; }
.gantt-task { padding: 10px 15px; border-bottom: 1px solid var(--gray-100); display: flex; flex-direction: column; gap: 4px; min-height: 60px; }.gantt-task a { color: var(--gray-900); overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }.gantt-task small { color: var(--main-color); display: block; font-size: 10px; }.gantt-task button { text-align: left; padding: 0; border: 0; background: transparent; color: var(--main-color); font-size: 11px; cursor: pointer; }
.gantt-track { position: relative; border-bottom: 1px solid var(--gray-100); min-height: 60px; }.gantt-track > span:not(.gantt-unplanned) { border-left: 1px solid var(--gray-100); }.gantt-bar { position: absolute; top: 22px; height: 16px; border-radius: 4px; background: #94a3b8; }.gantt-bar.status-in_progress { background: #3b82f6; }.gantt-bar.status-blocked { background: #f59e0b; }.gantt-bar.status-done { background: #10b981; }.gantt-unplanned { position: absolute; top: 21px; left: 12px; color: var(--gray-500); font-size: 11px; }
.view-empty { padding: 55px 20px; text-align: center; color: var(--gray-500); }.tasks-error { color: var(--color-error-700); margin: 12px 0; }
.task-form { display: flex; flex-direction: column; gap: 17px; padding-top: 8px; }.task-form label { display: flex; flex-direction: column; gap: 7px; color: var(--gray-700); font-weight: 600; font-size: 13px; }.field-title { color: var(--gray-700); }.field-title em { color: var(--color-error-700); font-style: normal; }.task-form label :deep(.ant-select) { width: 100%; }
.form-pair { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; }.form-actions { display: flex; justify-content: flex-end; gap: 9px; border-top: 1px solid var(--gray-150); padding-top: 16px; }
.code-setup { padding: 14px; border-radius: 9px; background: var(--gray-50, #f8fafc); border: 1px solid var(--gray-150); }.code-setup p { color: var(--gray-600); font-size: 12px; margin: 4px 0 10px; }.schedule-title { color: var(--gray-700); margin: 0; }
@media (max-width: 760px) { .tasks-content { padding: 18px 14px 40px; }.tasks-hero { align-items: flex-start; }.tasks-hero h1 { font-size: 23px; }.tasks-summary { grid-template-columns: repeat(2, 1fr); }.tasks-toolbar { flex-direction: column; align-items: stretch; }.tasks-filters { flex-wrap: wrap; }.tasks-search { width: 100%; }.tasks-board { grid-template-columns: repeat(5, 220px); }.form-pair { grid-template-columns: 1fr; } }
</style>
