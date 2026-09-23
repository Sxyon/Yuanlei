<template>
  <div class="project-dashboard-page">
    <PageHeader title="项目 Dashboard" :loading="loading" show-border>
      <template #actions>
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

      <div v-else-if="page.state === 'empty'" class="dashboard-state">
        <LayoutDashboard :size="32" />
        <p>该项目还没有 Dashboard 页面。</p>
        <a-button type="primary" @click="openEditor">在项目对话中生成</a-button>
      </div>

      <a-alert
        v-else-if="page.state === 'repair_required'"
        type="warning"
        show-icon
        message="页面未通过完整性或静态安全检查，暂不渲染"
        description="入口文件可能被通用工具直接修改、存在未提交写入，或包含第一版不支持的页面标记。请通过项目对话重新提交页面。"
      >
        <template #action>
          <a-button size="small" @click="load">刷新</a-button>
        </template>
      </a-alert>

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
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { LayoutDashboard, MessageSquarePlus, RefreshCw } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import { projectDashboardApi } from '@/apis/project_dashboard_api'
import { createDashboardSrcdoc } from '@/utils/dashboardFrame'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => String(route.params.project_id || ''))
const loading = ref(false)
const errorMessage = ref('')
const page = ref({ state: 'empty', revision: 0, sha256: null, size: null, html: null })
const srcdoc = ref('')
const frameKey = ref(0)

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
  loading.value = true
  errorMessage.value = ''
  try {
    const result = await projectDashboardApi.getDashboard(projectId.value)
    page.value = result
    srcdoc.value = result.state === 'ready' ? createDashboardSrcdoc(result.html) : ''
    frameKey.value += 1
  } catch (error) {
    console.error('Dashboard 加载失败:', error)
    page.value = { state: 'error', revision: 0, sha256: null, size: null, html: null }
    errorMessage.value = describeError(error)
  } finally {
    loading.value = false
  }
}

const openEditor = () => {
  router.push({ name: 'AgentComp', query: { project_id: projectId.value } })
}

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
</style>
