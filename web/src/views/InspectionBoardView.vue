<template>
  <div class="inspection-page">
    <PageHeader title="督查板" :loading="loading" show-border>
      <template #actions>
        <a-button size="small" :disabled="loading" @click="load">
          <template #icon><RefreshCw :size="14" /></template>
          刷新
        </a-button>
      </template>
    </PageHeader>

    <div class="inspection-body">
      <div v-if="loading" class="inspection-state">
        <a-spin />
        <p>正在加载督查板...</p>
      </div>

      <a-alert
        v-else-if="errorMessage"
        type="error"
        show-icon
        message="督查板加载失败"
        :description="errorMessage"
      >
        <template #action>
          <a-button size="small" @click="load">重试</a-button>
        </template>
      </a-alert>

      <template v-else>
        <div class="inspection-summary">
          <div v-for="card in summaryCards" :key="card.key" class="summary-card">
            <span class="summary-value">{{ card.value }}</span>
            <span class="summary-label">{{ card.label }}</span>
          </div>
        </div>

        <div v-if="boards.length" class="inspection-projects">
          <GovernanceBoardPanel
            v-for="board in boards"
            :key="board.project.id"
            :board="board"
            show-project-title
            project-link
          />
        </div>

        <a-empty v-else description="当前没有可见的项目督查板" />
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import GovernanceBoardPanel from '@/components/inspection/GovernanceBoardPanel.vue'
import { governanceBoardApi } from '@/apis/governance_board_api'
import { describeBoardError } from '@/utils/governanceBoard'

const loading = ref(false)
const errorMessage = ref('')
const board = ref({ generated_at: '', summary: null, projects: [] })

const boards = computed(() => board.value?.projects || [])

// 汇总数字全部来自读视图的 summary，前端不重新计算。
const summaryCards = computed(() => {
  const summary = board.value?.summary || {}
  return [
    { key: 'projects', label: '项目', value: summary.projects ?? boards.value.length },
    { key: 'open_topics', label: '研讨中议题', value: summary.open_topics ?? 0 },
    { key: 'pending_tasks', label: '待处理工作建议', value: summary.pending_tasks ?? 0 },
    { key: 'pending_decisions', label: '待决策', value: summary.pending_decisions ?? 0 },
    { key: 'blockers', label: '阻塞项', value: summary.blockers ?? 0 }
  ]
})

const load = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    board.value = await governanceBoardApi.getCrossProjectBoard()
  } catch (error) {
    console.error('督查板加载失败:', error)
    board.value = { generated_at: '', summary: null, projects: [] }
    errorMessage.value = describeBoardError(error)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
})
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
  gap: 16px;
  padding: var(--page-padding);
}

.inspection-state {
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

.inspection-summary {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: 12px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px 14px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-25);
}

.summary-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--gray-1000);
}

.summary-label {
  font-size: 12px;
  color: var(--gray-500);
}

.inspection-projects {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
