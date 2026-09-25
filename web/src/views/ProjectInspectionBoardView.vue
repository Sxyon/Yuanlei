<template>
  <div class="inspection-page">
    <PageHeader :title="pageTitle" :loading="loading" show-border>
      <template #actions>
        <a-button size="small" @click="router.push({ name: 'InspectionBoardComp' })">
          返回督查板
        </a-button>
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

      <GovernanceBoardPanel v-else :board="board" />
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { RefreshCw } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import GovernanceBoardPanel from '@/components/inspection/GovernanceBoardPanel.vue'
import { governanceBoardApi } from '@/apis/governance_board_api'
import { describeBoardError } from '@/utils/governanceBoard'

const route = useRoute()
const router = useRouter()

const projectId = computed(() => String(route.params.project_id || ''))
const loading = ref(false)
const errorMessage = ref('')
const board = ref({ project: null, governance: null, execution: null, generated_at: '' })

const pageTitle = computed(() =>
  board.value?.project?.name ? `${board.value.project.name} · 督查板` : '项目督查板'
)

const load = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    board.value = await governanceBoardApi.getProjectBoard(projectId.value)
  } catch (error) {
    console.error('督查板加载失败:', error)
    board.value = { project: null, governance: null, execution: null, generated_at: '' }
    errorMessage.value = describeBoardError(error)
  } finally {
    loading.value = false
  }
}

watch(projectId, () => {
  load()
})

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
</style>
