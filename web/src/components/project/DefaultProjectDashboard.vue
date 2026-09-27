<template>
  <div class="default-dashboard">
    <header class="overview-head">
      <div>
        <p class="eyebrow">项目概览 · 默认范式</p>
        <h1>{{ board.project?.name || '未命名项目' }}</h1>
        <p class="overview-description">从蓝图到执行，在这里查看项目当前进展。</p>
      </div>
      <RouterLink class="primary-link" :to="workbenchRoute"
        >进入项目工作台 <ArrowUpRight :size="16"
      /></RouterLink>
    </header>

    <div class="overview-stats" aria-label="项目待办概览">
      <div class="stat">
        <span>待审核议题</span><strong>{{ governance.pending_topics?.length || 0 }}</strong>
      </div>
      <div class="stat">
        <span>待审核任务</span><strong>{{ governance.pending_tasks?.length || 0 }}</strong>
      </div>
      <div class="stat">
        <span>近期阻塞记录</span><strong>{{ execution.blocked_runs?.length || 0 }}</strong>
      </div>
      <div class="stat">
        <span>项目汇报</span><strong>{{ governance.reports?.length || 0 }}</strong>
      </div>
    </div>

    <div class="overview-grid">
      <section class="overview-card blueprint-card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">01 / DIRECTION</p>
            <h2><BookOpen :size="18" /> 项目蓝图</h2>
          </div>
          <RouterLink :to="workbenchAnchor('blueprint')"
            >查看与编辑 <ArrowUpRight :size="14"
          /></RouterLink>
        </div>
        <div v-if="blueprints.length" class="document-tabs" aria-label="蓝图文档">
          <button
            v-for="doc in blueprints"
            :key="doc.name"
            type="button"
            :class="{ active: doc.name === selectedBlueprint }"
            @click="$emit('select-blueprint', doc.name)"
          >
            {{ doc.name }}
          </button>
        </div>
        <p v-if="blueprintError" class="inline-error">{{ blueprintError }}</p>
        <p v-else-if="blueprintLoading" class="empty-copy">正在读取蓝图…</p>
        <pre v-else-if="blueprintContent" class="blueprint-content">{{ blueprintContent }}</pre>
        <div v-else class="empty-block">
          <BookOpen :size="22" />
          <p>还没有蓝图内容</p>
          <RouterLink :to="workbenchAnchor('blueprint')">从项目目标开始填写</RouterLink>
        </div>
      </section>

      <section class="overview-card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">02 / DISCUSSION</p>
            <h2><MessagesSquare :size="18" /> 议题</h2>
          </div>
          <RouterLink :to="workbenchAnchor('topics')"
            >处理议题 <ArrowUpRight :size="14"
          /></RouterLink>
        </div>
        <ul v-if="governance.topics?.length" class="item-list">
          <li v-for="topic in latest(governance.topics, 5)" :key="topic.id">
            <div class="item-title">
              <strong>{{ topic.title }}</strong
              ><a-tag :color="governanceStatusColor(topic.status)">{{
                governanceStatusLabel(topic.status)
              }}</a-tag>
            </div>
            <p v-if="topic.summary">{{ topic.summary }}</p>
          </li>
        </ul>
        <p v-else class="empty-copy">暂无议题。可在工作台提出需要讨论的问题。</p>
      </section>

      <section class="overview-card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">03 / DELIVERY</p>
            <h2><ListTodo :size="18" /> 任务</h2>
          </div>
          <RouterLink :to="workbenchAnchor('tasks')"
            >管理任务 <ArrowUpRight :size="14"
          /></RouterLink>
        </div>
        <ul v-if="governance.tasks?.length" class="item-list">
          <li v-for="task in latest(governance.tasks, 5)" :key="task.id">
            <div class="item-title">
              <strong>{{ task.title }}</strong
              ><a-tag :color="governanceStatusColor(task.status)">{{
                governanceStatusLabel(task.status)
              }}</a-tag>
            </div>
            <p>
              {{ task.description || '暂无任务说明'
              }}<span v-if="task.assignee_agent_slug" class="item-meta">
                · {{ task.assignee_agent_slug }}</span
              >
            </p>
          </li>
        </ul>
        <p v-else class="empty-copy">暂无任务。确认议题后可创建待审核任务。</p>
      </section>

      <section class="overview-card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">04 / RECORD</p>
            <h2><ScrollText :size="18" /> 决策与汇报</h2>
          </div>
          <RouterLink :to="workbenchAnchor('reports')"
            >打开督查 <ArrowUpRight :size="14"
          /></RouterLink>
        </div>
        <div class="record-group">
          <h3>最近决策</h3>
          <ul v-if="governance.decisions?.length" class="item-list">
            <li v-for="decision in latest(governance.decisions, 3)" :key="decision.id">
              <strong>{{ decision.title }}</strong>
              <p>{{ decision.conclusion }}</p>
            </li>
          </ul>
          <p v-else class="empty-copy">暂无决策记录。</p>
        </div>
        <div class="record-group">
          <h3>最近汇报</h3>
          <ul v-if="governance.reports?.length" class="item-list">
            <li v-for="report in latest(governance.reports, 3)" :key="report.id">
              <strong>{{ report.title }}</strong>
              <p>{{ report.summary }}</p>
            </li>
          </ul>
          <p v-else class="empty-copy">暂无项目汇报。</p>
        </div>
      </section>
    </div>

    <section class="overview-card execution-card">
      <div class="card-heading">
        <div>
          <p class="eyebrow">05 / EXECUTION</p>
          <h2><Activity :size="18" /> 执行动态</h2>
        </div>
        <RouterLink :to="workbenchAnchor('tasks')">查看执行 <ArrowUpRight :size="14" /></RouterLink>
      </div>
      <div v-if="runStatuses.length" class="run-statuses">
        <span v-for="entry in runStatuses" :key="entry.status"
          >{{ entry.label }} {{ entry.count }}</span
        >
      </div>
      <ul v-if="execution.recent_runs?.length" class="run-list">
        <li v-for="run in execution.recent_runs.slice(0, 5)" :key="run.id">
          <strong>{{ run.agent_slug || '项目执行' }}</strong
          ><span>{{ runStatusLabel(run.status) }}</span>
        </li>
      </ul>
      <p v-else class="empty-copy">暂无执行记录。审核任务后可在工作台委派。</p>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { Activity, ArrowUpRight, BookOpen, ListTodo, MessagesSquare, ScrollText } from '@lucide/vue'
import {
  governanceStatusColor,
  governanceStatusLabel,
  runStatusEntries,
  runStatusLabel
} from '@/utils/governanceBoard'

const props = defineProps({
  projectId: { type: String, required: true },
  board: { type: Object, required: true },
  blueprints: { type: Array, default: () => [] },
  selectedBlueprint: { type: String, default: '' },
  blueprintContent: { type: String, default: '' },
  blueprintLoading: { type: Boolean, default: false },
  blueprintError: { type: String, default: '' }
})
defineEmits(['select-blueprint'])

const governance = computed(() => props.board.governance || {})
const execution = computed(() => props.board.execution || {})
const runStatuses = computed(() => runStatusEntries(execution.value.run_status_counts))
const workbenchRoute = computed(() => ({
  name: 'ProjectInspectionBoardComp',
  params: { project_id: props.projectId }
}))
const workbenchAnchor = (anchor) => ({ ...workbenchRoute.value, hash: `#${anchor}` })
/** 治理列表由后端按创建顺序返回，概览优先显示最新条目。 */
const latest = (items, limit) => (items || []).slice(-limit).reverse()
</script>

<style scoped lang="less">
.default-dashboard {
  width: min(1320px, 100%);
  margin: 0 auto;
  display: grid;
  gap: 16px;
  padding-bottom: 28px;
}
.overview-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 28px 30px;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: var(--gray-0);
}
.eyebrow {
  margin: 0 0 10px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.overview-head h1 {
  margin: 0;
  color: var(--gray-1000);
  font-size: clamp(24px, 3vw, 32px);
  line-height: 1.25;
}
.overview-description {
  margin: 10px 0 0;
  color: var(--gray-600);
}
.primary-link {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  flex-shrink: 0;
  padding: 9px 14px;
  border-radius: 7px;
  background: var(--main-color);
  color: var(--gray-0);
  font-weight: 600;
}
.primary-link:hover {
  color: var(--gray-0);
  background: var(--main-600);
}
.overview-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}
.stat {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 22px;
}
.stat + .stat {
  border-left: 1px solid var(--gray-150);
}
.stat span {
  color: var(--gray-600);
  font-size: 13px;
}
.stat strong {
  color: var(--gray-1000);
  font-size: 25px;
  line-height: 1;
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.overview-card {
  min-width: 0;
  padding: 22px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}
.card-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 14px;
  margin-bottom: 18px;
}
.card-heading h2 {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0;
  color: var(--gray-1000);
  font-size: 17px;
}
.card-heading a {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  flex-shrink: 0;
  font-size: 13px;
}
.document-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
  margin-bottom: 12px;
  padding-bottom: 4px;
}
.document-tabs button {
  padding: 6px 9px;
  border: 1px solid var(--gray-150);
  border-radius: 6px;
  background: var(--gray-0);
  color: var(--gray-600);
  cursor: pointer;
  white-space: nowrap;
}
.document-tabs button.active {
  border-color: var(--main-color);
  background: var(--main-30);
  color: var(--main-color);
}
.blueprint-content {
  max-height: 260px;
  min-height: 130px;
  overflow: auto;
  margin: 0;
  padding: 15px;
  border-radius: 7px;
  background: var(--gray-25);
  color: var(--gray-800);
  font: inherit;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
.empty-block {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
  min-height: 130px;
  padding: 20px;
  border-radius: 7px;
  background: var(--gray-25);
  color: var(--gray-500);
}
.empty-block p {
  margin: 0;
  color: var(--gray-700);
}
.item-list {
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}
.item-list li {
  min-width: 0;
  padding: 11px 0;
  border-top: 1px solid var(--gray-100);
}
.item-list strong {
  color: var(--gray-900);
  font-weight: 600;
  overflow-wrap: anywhere;
}
.item-list p {
  margin: 5px 0 0;
  color: var(--gray-600);
  font-size: 13px;
  line-height: 1.55;
  overflow-wrap: anywhere;
}
.item-title {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.item-title :deep(.ant-tag) {
  margin-right: 0;
  flex-shrink: 0;
}
.item-meta {
  color: var(--gray-500);
}
.record-group + .record-group {
  margin-top: 14px;
}
.record-group h3 {
  margin: 0 0 6px;
  color: var(--gray-700);
  font-size: 13px;
}
.empty-copy {
  margin: 0;
  padding: 12px 0;
  color: var(--gray-500);
  font-size: 13px;
}
.inline-error {
  color: var(--color-error-700);
  font-size: 13px;
}
.run-statuses {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.run-statuses span {
  padding: 4px 9px;
  border-radius: 5px;
  background: var(--gray-50);
  color: var(--gray-700);
  font-size: 12px;
}
.run-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.run-list li {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 0;
  border-top: 1px solid var(--gray-100);
  color: var(--gray-600);
  font-size: 13px;
}
.run-list strong {
  color: var(--gray-900);
}
@media (max-width: 900px) {
  .overview-stats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .stat:nth-child(3) {
    border-left: 0;
    border-top: 1px solid var(--gray-150);
  }
  .stat:nth-child(4) {
    border-top: 1px solid var(--gray-150);
  }
}
@media (max-width: 680px) {
  .overview-head {
    align-items: flex-start;
    flex-direction: column;
    padding: 22px;
  }
  .overview-grid {
    grid-template-columns: 1fr;
  }
  .run-list {
    grid-template-columns: 1fr;
  }
  .stat {
    padding: 14px;
  }
  .stat span {
    font-size: 12px;
  }
  .stat strong {
    font-size: 20px;
  }
}
</style>
