<template>
  <div class="project-dashboard-page">
    <PageHeader title="项目概览" :loading="loading" show-border>
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

    <div ref="scrollContainer" class="dashboard-body">
        <div class="dashboard-modes" aria-label="项目概览视图">
          <button type="button" :aria-pressed="!business" @click="setView(false)">管理概览</button>
          <button type="button" :aria-pressed="business" @click="setView(true)">业务大屏</button>
          <span>管理概览发现待办；业务大屏用于观察，办理进入工作详情。</span>
        </div>
        <template v-if="!business">
        <div v-if="boardLoading && !board.project" class="dashboard-state" role="status"><a-spin /><p>正在读取管理概览…</p></div>
        <a-alert
          v-else-if="boardError && !board.project"
          type="error"
          show-icon
          message="项目概览加载失败"
          :description="boardError"
        >
          <template #action><a-button size="small" @click="load">重试</a-button></template>
        </a-alert>
        <div v-else>
        <a-alert v-if="boardError" type="error" show-icon :message="boardError" />
        <p v-if="boardLoading" role="status">正在刷新管理概览，当前内容保留。</p>
        <DefaultProjectDashboard
          :project-id="projectId"
          :board="board"
          :blueprints="blueprints"
          :selected-blueprint="selectedBlueprint"
          :blueprint-content="blueprintContent"
          :blueprint-loading="blueprintLoading"
          :blueprint-error="blueprintError"
          @select-blueprint="selectBlueprint"
        />
        </div>
        </template>
        <template v-else>
          <div v-if="businessLoading" class="dashboard-state" role="status"><a-spin /><p>正在读取业务页面；管理概览可独立使用。</p></div>
          <a-alert v-else-if="errorMessage" type="error" show-icon message="业务大屏加载失败；管理概览仍可进入" :description="errorMessage"><template #action><a-button @click="load">重试</a-button></template></a-alert>
          <a-alert v-else-if="page.state !== 'ready'" type="info" show-icon :message="page.state === 'repair_required' ? '业务页面需要修复' : '尚无业务大屏'" description="通过项目对话维护静态页面，继续使用管理概览办理。" />
          <div v-else class="dashboard-frame-wrap">
          <p class="dashboard-meta">当前为静态 HTML：无动态取数或业务钻取；页面显示的数据时间由内容说明。</p>
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
        </template>
    </div>
  </div>
</template>

<script setup>
import { useReturnScroll } from '@/utils/pageReturnScroll'
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
const business = computed(() => route.query.view === 'business')
const setView = (show) => router.replace({ query: { ...route.query, view: show ? 'business' : undefined } })
const loading = ref(false), boardLoading = ref(false), businessLoading = ref(false)
const scrollContainer = ref(null)
useReturnScroll(computed(() => business.value ? businessLoading.value : boardLoading.value), () => scrollContainer.value)
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
  const sameProject = board.value.project?.id === project
  if (!sameProject) {
    board.value = { project: null, governance: null, execution: null }
    blueprints.value = []
    selectedBlueprint.value = ''
    blueprintContent.value = ''
  }
  boardLoading.value = true
  businessLoading.value = true
  blueprintLoading.value = true
  const current = () => seq === loadSeq && projectId.value === project
  await Promise.allSettled([
    (async () => {
      try {
        const result = await projectDashboardApi.getDashboard(project)
        if (!current()) return
        page.value = result
        srcdoc.value = result.state === 'ready' ? createDashboardSrcdoc(result.html) : ''
        frameKey.value += 1
      } catch (failure) {
        if (!current()) return
        page.value = { state: 'error', revision: 0 }
        srcdoc.value = ''
        errorMessage.value = describeError(failure)
      } finally { if (current()) businessLoading.value = false }
    })(),
    (async () => {
      try {
        const result = await governanceBoardApi.getProjectBoard(project)
        if (current()) board.value = result
      } catch (failure) {
        if (current()) {
          boardError.value = describeBoardError(failure)
          if ([401, 403, 404].includes(failure?.status)) { board.value = { project: null }; blueprintContent.value = '' }
        }
      }
      finally { if (current()) boardLoading.value = false }
    })(),
    (async () => {
      try {
        const result = await governanceBoardApi.listBlueprints(project)
        if (!current()) return
        blueprints.value = result.documents || []
        if (blueprints.value.length) void readBlueprint(blueprints.value.find(item => item.name === (route.query.blueprint || selectedBlueprint.value))?.name || blueprints.value[0].name)
        else { blueprintLoading.value = false; selectedBlueprint.value = ''; blueprintContent.value = '' }
      } catch (failure) {
        if (current()) { blueprintError.value = describeBoardError(failure); blueprintLoading.value = false }
      }
    })()
  ])
  if (current()) loading.value = false

}

const selectBlueprint = (name) => {
  router.replace({ query: { ...route.query, blueprint: name } })
  return readBlueprint(name)
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

.dashboard-modes { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; button { border: 1px solid var(--gray-200); border-radius: 6px; padding: 8px 14px; background: var(--gray-0); color: var(--gray-800); cursor: pointer; } button[aria-pressed="true"] { color: var(--main-color); border-color: var(--main-color); background: var(--main-10); } span { color: var(--gray-600); font-size: 12px; } }

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
