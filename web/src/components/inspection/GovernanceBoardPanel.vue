<template>
  <section class="board-panel">
    <header v-if="showProjectTitle" class="board-panel-head">
      <h2 class="board-panel-title">
        <RouterLink
          v-if="projectLink && projectId"
          :to="{ name: 'ProjectInspectionBoardComp', params: { project_id: projectId } }"
          class="board-project-link"
        >
          {{ projectName }}
        </RouterLink>
        <template v-else>{{ projectName }}</template>
      </h2>
      <span v-if="generatedAt" class="board-panel-time">生成于 {{ generatedAt }}</span>
    </header>

    <div class="board-grid">
      <div class="board-section">
        <h3 class="board-section-title">待决策队列</h3>
        <div v-for="group in pendingGroups" :key="group.key" class="pending-group">
          <p class="pending-group-label">{{ group.label }}（{{ group.items.length }}）</p>
          <ul v-if="group.items.length" class="board-list">
            <li v-for="item in group.items" :key="item.id" class="board-list-item">
              <div class="board-item-main">
                <span class="board-item-title">{{ item.title }}</span>
                <a-tag :color="governanceTagColor(item.status)">
                  {{ governanceStatusLabel(item.status) }}
                </a-tag>
              </div>
              <p v-if="itemNote(item)" class="board-item-note">{{ itemNote(item) }}</p>
              <div class="board-item-meta">
                <span v-if="item.source?.channel">{{ sourceChannelLabel(item.source.channel) }}</span>
                <span v-if="item.assignee_agent_slug">执行 {{ item.assignee_agent_slug }}</span>
                <span v-if="item.created_at">{{ item.created_at }}</span>
              </div>
            </li>
          </ul>
          <p v-else class="board-empty">无</p>
        </div>
      </div>

      <div class="board-section">
        <h3 class="board-section-title">阻塞项（{{ blockedRuns.length }}）</h3>
        <ul v-if="blockedRuns.length" class="board-list">
          <li v-for="run in blockedRuns" :key="run.id" class="board-list-item">
            <div class="board-item-main">
              <span class="board-item-title">{{ run.agent_slug || run.id }}</span>
              <a-tag color="red">{{ runStatusLabel(run.status) }}</a-tag>
            </div>
            <p v-if="run.error_message" class="board-item-note">{{ run.error_message }}</p>
            <div class="board-item-meta">
              <span v-if="run.error_type">{{ run.error_type }}</span>
              <span v-if="run.finished_at || run.created_at">
                {{ run.finished_at || run.created_at }}
              </span>
            </div>
          </li>
        </ul>
        <p v-else class="board-empty">无阻塞项</p>
      </div>
    </div>

    <div v-if="runStatuses.length" class="board-run-status">
      <a-tag v-for="entry in runStatuses" :key="entry.status">
        {{ entry.label }} {{ entry.count }}
      </a-tag>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import {
  governanceStatusLabel,
  runStatusEntries,
  runStatusLabel,
  sourceChannelLabel
} from '@/utils/governanceBoard'

const props = defineProps({
  board: { type: Object, required: true },
  showProjectTitle: { type: Boolean, default: false },
  projectLink: { type: Boolean, default: false }
})

const governance = computed(() => props.board?.governance || {})
const projectId = computed(() => props.board?.project?.id || '')
const projectName = computed(() => props.board?.project?.name || '未命名项目')
const generatedAt = computed(() => props.board?.generated_at || '')
const blockedRuns = computed(() => props.board?.execution?.blocked_runs || [])
const runStatuses = computed(() => runStatusEntries(props.board?.execution?.run_status_counts))

// 待决策队列直接按读视图给出的 pending_* 分组，前端不再自行筛选状态。
const pendingGroups = computed(() => [
  { key: 'topics', label: '待审核议题', items: governance.value.pending_topics || [] },
  { key: 'tasks', label: '待审核任务', items: governance.value.pending_tasks || [] },
  { key: 'decisions', label: '待决策', items: governance.value.pending_decisions || [] }
])

const itemNote = (item) => item.summary || item.description || item.conclusion || ''

const governanceTagColor = (status) => {
  if (status === 'rejected') return 'red'
  if (status === 'canonical' || status === 'implemented') return 'green'
  return 'gold'
}
</script>

<style scoped lang="less">
.board-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}

.board-panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}

.board-panel-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--gray-1000);
}

.board-project-link {
  color: var(--main-color);
  text-decoration: none;

  &:hover {
    text-decoration: underline;
  }
}

.board-panel-time {
  color: var(--gray-500);
  font-size: 12px;
}

.board-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.board-section-title {
  margin: 0 0 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--gray-700);
}

.pending-group + .pending-group {
  margin-top: 10px;
}

.pending-group-label {
  margin: 0 0 4px;
  font-size: 12px;
  color: var(--gray-500);
}

.board-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.board-list-item {
  padding: 8px 10px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
  background: var(--gray-25);
}

.board-item-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.board-item-title {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--gray-1000);
  word-break: break-word;
}

.board-item-note {
  margin: 4px 0 0;
  font-size: 12px;
  color: var(--gray-600);
  word-break: break-word;
}

.board-item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 4px;
  font-size: 12px;
  color: var(--gray-500);
}

.board-empty {
  margin: 0;
  font-size: 12px;
  color: var(--gray-400);
}

.board-run-status {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
</style>
