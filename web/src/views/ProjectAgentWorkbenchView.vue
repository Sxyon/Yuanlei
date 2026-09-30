<template>
  <div class="agent-workbench-page">
    <PageHeader :title="workbenchTitle" :loading="loading" show-border>
      <template #actions><a-button size="small" @click="load">刷新</a-button></template>
    </PageHeader>
    <main class="agent-workbench-content">
      <a-spin v-if="loading" class="agent-workbench-state" />
      <a-alert v-else-if="error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <template v-else-if="workbench">
        <section class="agent-workbench-section agent-workbench-config">
          <h2>任务接收设置</h2>
          <label class="agent-workbench-setting">
            <span>自动接受新分配的任务</span>
            <a-switch v-model:checked="autoAcceptWork" :disabled="settingsSaving" />
          </label>
          <div class="agent-workbench-setting agent-workbench-model">
            <span>任务默认模型</span>
            <ModelSelectorComponent
              :model_spec="workDefaultModelSpec"
              clearable
              :disabled="settingsSaving"
              @select-model="selectWorkModel"
            />
          </div>
          <p class="agent-workbench-muted">未选择时使用该智能体的项目模型。接受任务时固化模型，后续设置变更不影响已接受任务。</p>
          <a-button type="primary" :loading="settingsSaving" :disabled="!settingsChanged || settingsSaving" @click="saveSettings">保存设置</a-button>
        </section>
        <section v-for="section in sections" :key="section.key" class="agent-workbench-section">
          <h2>{{ section.title }}</h2>
          <p v-if="!section.items.length" class="agent-workbench-muted">{{ section.empty }}</p>
          <ul v-else>
            <li v-for="item in section.items" :key="item.id">
              <div>
                <RouterLink :to="{ name: 'ProjectWorkTaskView', params: { project_id: route.params.project_id, task_id: item.task_id } }">
                  {{ item.task_number }} · {{ item.task_title }}
                </RouterLink>
                <p>{{ statusLabel(item.status) }} · {{ formatTime(item.created_at) }}</p>
                <p v-if="item.model_spec">执行模型：{{ item.model_spec }}</p>
                <p v-if="item.current_run_id">Run：{{ item.current_run_id }}</p>
                <p v-if="item.error_message" class="agent-workbench-error">{{ item.error_message }}</p>
                <RouterLink v-if="item.thread_id && ['submitted', 'interrupted'].includes(item.status)" :to="{ name: 'AgentCompWithThreadId', params: { thread_id: item.thread_id } }">进入执行会话</RouterLink>
              </div>
              <div v-if="['pending_acceptance', 'queued'].includes(item.status)" class="agent-workbench-actions">
                <a-button v-if="item.status === 'pending_acceptance'" type="primary" :loading="working === item.id" :disabled="Boolean(working)" @click="accept(item)">接受任务</a-button>
                <a-button :loading="working === item.id" :disabled="Boolean(working)" @click="cancel(item)">撤回分配</a-button>
              </div>
              <div v-else-if="['failed', 'cancelled'].includes(item.status)" class="agent-workbench-actions">
                <a-button :loading="working === item.id" :disabled="Boolean(working)" @click="retry(item)">重新执行</a-button>
              </div>
            </li>
          </ul>
        </section>
        <p v-if="actionError" class="agent-workbench-error" role="alert">{{ actionError }}</p>
      </template>
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import { projectWorkExecutionApi } from '@/apis/project_work_execution_api'
import { projectAgentApi } from '@/apis/project_agent_api'

const route = useRoute()
const workbench = ref(null)
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const working = ref(null)
const settingsSaving = ref(false)
const autoAcceptWork = ref(false)
const workDefaultModelSpec = ref('')
const agentName = ref('')
let loadVersion = 0

const workbenchTitle = computed(() => {
  const subject = agentName.value || route.params.agent_slug
  return subject ? `智能体工作台 · ${subject}` : '智能体工作台'
})

const settingsChanged = computed(() => workbench.value && (
  autoAcceptWork.value !== workbench.value.auto_accept_work ||
  workDefaultModelSpec.value !== (workbench.value.work_default_model_spec || '')
))
const selectWorkModel = (spec) => { workDefaultModelSpec.value = spec || '' }

const sections = computed(() => [
  { key: 'current', title: '当前工作', items: workbench.value?.current ? [workbench.value.current] : [], empty: '当前没有执行中的任务' },
  { key: 'pending_acceptance', title: '待接受', items: workbench.value?.pending_acceptance || [], empty: '没有待接受任务' },
  { key: 'queued', title: '排队任务', items: workbench.value?.queued || [], empty: '队列为空' },
  { key: 'recent', title: '最近工作', items: workbench.value?.recent || [], empty: '暂无历史记录' }
])
const statusLabel = (status) => ({
  pending_acceptance: '待接受', queued: '排队中', dispatching: '派发中', submitted: '执行中',
  interrupted: '等待答复', completed: '已完成', failed: '失败', cancelled: '已取消'
})[status] || status
const formatTime = (value) => (value ? new Date(value).toLocaleString('zh-CN') : '')

async function load() {
  const projectId = route.params.project_id
  const agentSlug = route.params.agent_slug
  if (!projectId || !agentSlug) {
    ++loadVersion
    loading.value = false
    return
  }
  const version = ++loadVersion
  loading.value = true
  error.value = ''
  try {
    const [result, bindings] = await Promise.all([
      projectWorkExecutionApi.getWorkbench(projectId, agentSlug),
      // 显示名降级为 slug，不因归属列表读取失败阻断工作台本身。
      projectAgentApi.list(projectId).then((data) => data.agents || []).catch(() => [])
    ])
    if (version === loadVersion) {
      workbench.value = result
      autoAcceptWork.value = Boolean(result.auto_accept_work)
      workDefaultModelSpec.value = result.work_default_model_spec || ''
      agentName.value = bindings.find((agent) => agent.slug === agentSlug)?.name || ''
    }
  } catch (cause) {
    if (version === loadVersion) error.value = cause?.message || '工作台加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function saveSettings() {
  const projectId = route.params.project_id
  const agentSlug = route.params.agent_slug
  if (!projectId || !agentSlug || !settingsChanged.value || settingsSaving.value) return
  settingsSaving.value = true
  actionError.value = ''
  try {
    await projectWorkExecutionApi.updateWorkbenchConfig(projectId, agentSlug, {
      auto_accept_work: autoAcceptWork.value,
      work_default_model_spec: workDefaultModelSpec.value || null
    })
    if (projectId === route.params.project_id && agentSlug === route.params.agent_slug) await load()
  } catch (cause) {
    actionError.value = cause?.message || '保存任务设置失败'
  } finally {
    settingsSaving.value = false
  }
}

async function accept(item) {
  if (working.value) return
  const version = loadVersion
  working.value = item.id
  actionError.value = ''
  try {
    await projectWorkExecutionApi.accept(route.params.project_id, route.params.agent_slug, item.id)
    if (version === loadVersion) await load()
  } catch (cause) {
    if (version === loadVersion) actionError.value = cause?.message || '接受任务失败'
  } finally {
    working.value = null
  }
}

async function cancel(item) {
  if (working.value) return
  const version = loadVersion
  working.value = item.id
  actionError.value = ''
  try {
    await projectWorkExecutionApi.cancel(route.params.project_id, item.task_id, item.id)
    if (version === loadVersion) await load()
  } catch (cause) {
    if (version === loadVersion) actionError.value = cause?.message || '撤回分配失败'
  } finally {
    working.value = null
  }
}

async function retry(item) {
  if (working.value) return
  const version = loadVersion
  working.value = item.id
  actionError.value = ''
  try {
    await projectWorkExecutionApi.assign(route.params.project_id, item.task_id, item.agent_slug)
    if (version === loadVersion) await load()
  } catch (cause) {
    if (version === loadVersion) actionError.value = cause?.message || '重新执行失败'
  } finally {
    working.value = null
  }
}

watch(() => [route.params.project_id, route.params.agent_slug], () => {
  if (!route.params.project_id || !route.params.agent_slug) {
    ++loadVersion
    loading.value = false
    return
  }
  workbench.value = null
  actionError.value = ''
  agentName.value = ''
  load()
}, { immediate: true })
</script>

<style scoped lang="less">
.agent-workbench-content { max-width: 920px; margin: 0 auto; padding: 24px; }
.agent-workbench-state { display: block; margin: 56px auto; }
.agent-workbench-section { border-bottom: 1px solid var(--gray-150); padding: 12px 0 22px; }
.agent-workbench-section h2 { font-size: 17px; color: var(--gray-900); }
.agent-workbench-setting { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin: 14px 0; }
.agent-workbench-setting > span { flex: 1; }
.agent-workbench-model > :last-child { flex: 2; }
.agent-workbench-section ul { list-style: none; padding: 0; }
.agent-workbench-section li { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 12px 0; border-top: 1px solid var(--gray-100); }
.agent-workbench-actions { display: flex; gap: 8px; }
.agent-workbench-section p { margin: 5px 0; color: var(--gray-500); }
.agent-workbench-muted { color: var(--gray-500); }
.agent-workbench-error { color: var(--color-error-700) !important; }
</style>
