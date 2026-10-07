<template>
  <div class="project-dashboard-page">
    <PageHeader title="项目 Dashboard" :loading="loading" show-border>
      <template #actions>
        <a-button size="small" @click="openWorkbench">项目工作台</a-button>
        <a-button size="small" :disabled="loading" @click="load">
          <template #icon><RefreshCw :size="14" /></template>
          刷新
        </a-button>
        <a-button type="primary" size="small" @click="openEditor">
          <template #icon><MessageSquarePlus :size="14" /></template>
          在项目对话中编辑
        </a-button>
      </template>
    </PageHeader>

    <div class="dashboard-body">
      <div v-if="loading" class="dashboard-state">
        <a-spin />
        <p>正在加载 Dashboard...</p>
      </div>

      <a-alert
        v-else-if="errorMessage"
        type="error"
        show-icon
        message="Dashboard 加载失败"
        :description="errorMessage"
      >
        <template #action>
          <a-button size="small" @click="load">重试</a-button>
        </template>
      </a-alert>

      <template v-else-if="page.state === 'empty' || page.state === 'repair_required'">
        <a-alert
          v-if="page.state === 'repair_required'"
          type="warning"
          show-icon
          message="自定义页面需要修复，当前展示项目默认概览"
          description="自定义页面未通过完整性或静态安全检查。请通过项目对话重新提交页面。"
        />
        <a-alert
          v-if="boardError"
          type="error"
          show-icon
          message="项目概览加载失败"
          :description="boardError"
        >
          <template #action><a-button size="small" @click="load">重试</a-button></template>
        </a-alert>
        <DefaultProjectDashboard
          v-else
          :project-id="projectId"
          :board="board"
          :blueprints="blueprints"
          :selected-blueprint="selectedBlueprint"
          :blueprint-content="blueprintContent"
          :blueprint-loading="blueprintLoading"
          :blueprint-error="blueprintError"
          @select-blueprint="readBlueprint"
        />
      </template>

      <div v-else class="dashboard-frame-wrap">
        <iframe
          :key="frameKey"
          class="dashboard-frame"
          :srcdoc="srcdoc"
          sandbox
          referrerpolicy="no-referrer"
        ></iframe>
        <p class="dashboard-meta">
          revision {{ page.revision }} · sha256 {{ shortHash }} · {{ page.size }} bytes
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onActivated, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { MessageSquarePlus, RefreshCw } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import DefaultProjectDashboard from '@/components/project/DefaultProjectDashboard.vue'
import { projectDashboardApi } from '@/apis/project_dashboard_api'
import { governanceBoardApi } from '@/apis/governance_board_api'
import { createDashboardSrcdoc } from '@/utils/dashboardFrame'
import { describeBoardError } from '@/utils/governanceBoard'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => String(route.params.project_id || ''))
const loading = ref(false)
const errorMessage = ref('')
const page = ref({ state: 'empty', revision: 0, sha256: null, size: null, html: null })
const srcdoc = ref('')
const frameKey = ref(0)
const board = ref({ project: null, governance: null, execution: null })
const boardError = ref('')
const blueprints = ref([])
const selectedBlueprint = ref('')
const blueprintContent = ref('')
const blueprintError = ref('')
const blueprintLoading = ref(false)
let loadSeq = 0
let blueprintSeq = 0

const shortHash = computed(() =>
  typeof page.value.sha256 === 'string' ? page.value.sha256.slice(0, 12) : '-'
)

const describeError = (error) => {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') return detail.message || 'Dashboard 加载失败'
  return error?.message || 'Dashboard 加载失败'
}

const load = async () => {
  const project = projectId.value
  const seq = ++loadSeq
  blueprintSeq += 1
  loading.value = true
  errorMessage.value = ''
  boardError.value = ''
  blueprintError.value = ''
  blueprintLoading.value = false
  board.value = { project: null, governance: null, execution: null }
  blueprints.value = []
  selectedBlueprint.value = ''
  blueprintContent.value = ''
  try {
    const result = await projectDashboardApi.getDashboard(project)
    if (seq !== loadSeq || projectId.value !== project) return
    page.value = result
    srcdoc.value = result.state === 'ready' ? createDashboardSrcdoc(result.html) : ''
    frameKey.value += 1
    if (result.state === 'empty' || result.state === 'repair_required') {
      const [boardResult, docsResult] = await Promise.allSettled([
        governanceBoardApi.getProjectBoard(project),
        governanceBoardApi.listBlueprints(project)
      ])
      if (seq !== loadSeq || projectId.value !== project) return
      if (boardResult.status === 'fulfilled') board.value = boardResult.value
      else boardError.value = describeBoardError(boardResult.reason)
      if (docsResult.status === 'fulfilled') {
        blueprints.value = docsResult.value.documents || []
        if (blueprints.value.length) await readBlueprint(blueprints.value[0].name)
      } else blueprintError.value = describeBoardError(docsResult.reason)
    }
  } catch (error) {
    if (seq !== loadSeq || projectId.value !== project) return
    console.error('Dashboard 加载失败:', error)
    page.value = { state: 'error', revision: 0, sha256: null, size: null, html: null }
    errorMessage.value = describeError(error)
  } finally {
    if (seq === loadSeq && projectId.value === project) loading.value = false
  }
}

/** 读取选中的蓝图，忽略过期项目与文档请求。 */
const readBlueprint = async (name) => {
  const project = projectId.value
  const seq = ++blueprintSeq
  selectedBlueprint.value = name
  blueprintLoading.value = true
  blueprintError.value = ''
  blueprintContent.value = ''
  try {
    const document = await governanceBoardApi.getBlueprint(project, name)
    if (seq !== blueprintSeq || projectId.value !== project) return
    blueprintContent.value = document.content || ''
  } catch (error) {
    if (seq !== blueprintSeq || projectId.value !== project) return
    blueprintError.value = describeBoardError(error)
  } finally {
    if (seq === blueprintSeq && projectId.value === project) blueprintLoading.value = false
  }
}

const openEditor = () => {
  router.push({ name: 'AgentComp', query: { project_id: projectId.value } })
}

const openWorkbench = () => {
  router.push({ name: 'ProjectInspectionBoardComp', params: { project_id: projectId.value } })
}

let hasActivated = false
onActivated(() => {
  if (hasActivated) load()
  hasActivated = true
})
watch(projectId, load)
onMounted(() => {
  load()
})
</script>

<style scoped lang="less">
.project-dashboard-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

.dashboard-body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: var(--page-padding);
  overflow: auto;
  background: var(--gray-25);
}

.dashboard-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 48px 16px;
  color: var(--gray-600);

  p {
    margin: 0;
  }
}

.dashboard-frame-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.dashboard-frame {
  flex: 1;
  width: 100%;
  min-height: 320px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  background: var(--gray-0);
}

.dashboard-meta {
  margin: 6px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}

@media (max-width: 680px) {
  :deep(.page-header) {
    height: auto;
    flex-wrap: wrap;
    gap: 8px;
    padding: 12px;
  }
  :deep(.page-header-right) {
    flex-wrap: wrap;
  }
}
</style>
