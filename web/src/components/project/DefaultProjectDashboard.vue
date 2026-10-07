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

    <div class="overview-stats" aria-label="正式工作概览">
      <section v-for="group in groups" :key="group.key" class="overview-card summary-group">
        <div class="card-heading">
          <h2>{{ group.title }}</h2>
          <a-button type="link" @click="openList(group.key, group.title)">更多</a-button>
        </div>
        <p class="summary-count">{{ group.count }}</p>
        <p class="item-meta">{{ group.note }}</p>
        <ul v-if="group.items.length" class="item-list">
          <li v-for="item in group.items" :key="item.id">
            <RouterLink :to="item.url">{{ itemLabel(item) }}</RouterLink>
            <p>{{ detailLabel(item) }}</p>
          </li>
        </ul>
        <p v-else class="empty-copy">暂无{{ group.title }}记录。</p>
      </section>
    </div>
    <p class="item-meta">
      统计日期 {{ overview.as_of_date }} · 截止日期按
      {{ overview.timezone || 'UTC' }} 判断；受阻与逾期可交叉，已结束工作不计逾期。
    </p>
    <a-modal v-model:open="listOpen" :title="listTitle" :footer="null" @cancel="closeList">
      <a-spin v-if="listLoading" />
      <a-alert v-else-if="listError" type="error" show-icon :message="listError"
        ><template #action
          ><a-button @click="loadList(listOffset)">重试</a-button></template
        ></a-alert
      >
      <template v-else>
        <p>共 {{ listPage.total || 0 }} 条</p>
        <ul class="item-list">
          <li v-for="item in listPage.items || []" :key="item.id">
            <RouterLink :to="item.url" @click="closeList">{{ itemLabel(item) }}</RouterLink>
            <p>{{ detailLabel(item) }}</p>
          </li>
        </ul>
        <p v-if="!listPage.items?.length" class="empty-copy">暂无记录。</p>
        <a-pagination
          :current="Math.floor(listOffset / 20) + 1"
          :page-size="20"
          :total="listPage.total || 0"
          :show-size-changer="false"
          @change="(page) => loadList((page - 1) * 20)"
        />
      </template>
    </a-modal>

    <ProjectGovernanceGraph
      :project-id="projectId"
      :governance="governance"
      :graph="board.graph || {}"
    />

    <section v-if="effectiveDecisions.length" class="overview-card decision-summary">
      <div class="card-heading">
        <div>
          <p class="eyebrow">03 / DECISIONS</p>
          <h2><ScrollText :size="18" /> 近期有效决策</h2>
        </div>
        <RouterLink :to="workbenchAnchor('decisions')"
          >查看全部 <ArrowUpRight :size="14"
        /></RouterLink>
      </div>
      <div class="decision-summary-list">
        <article
          v-for="decision in latest(effectiveDecisions, 3)"
          :key="decision.id"
          class="decision-summary-item"
        >
          <header>
            <RouterLink :to="workbenchRecord({ decision_id: decision.id })">{{
              decision.title
            }}</RouterLink>
            <span>{{ governanceStatusLabel(decision.status) }}</span>
          </header>
          <a-alert
            v-if="decision.topic_execution_hint === 'pause_recommended'"
            type="warning"
            show-icon
            message="关联议题建议暂停原方案"
            description="仅为议题提示，不撤销决策或暂停任务或执行记录。"
          />
          <MarkdownPreview :content="decision.conclusion" compact />
        </article>
      </div>
    </section>

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
            {{ displayBlueprintName(doc.name) }}
          </button>
        </div>
        <p v-if="blueprintError" class="inline-error">{{ blueprintError }}</p>
        <p v-else-if="blueprintLoading" class="empty-copy">正在读取蓝图…</p>
        <div v-else-if="blueprintContent" class="blueprint-content">
          <MarkdownPreview :content="blueprintContent" />
        </div>
        <div v-else class="empty-block">
          <BookOpen :size="22" />
          <p>还没有蓝图内容</p>
          <RouterLink :to="workbenchAnchor('blueprint')">从项目目标开始填写</RouterLink>
        </div>
      </section>

      <section class="overview-card">
        <div class="card-heading">
          <div>
            <p class="eyebrow">03 / RECORD</p>
            <h2><ScrollText :size="18" /> 项目汇报</h2>
          </div>
          <RouterLink :to="workbenchAnchor('reports')"
            >打开督查 <ArrowUpRight :size="14"
          /></RouterLink>
        </div>
        <ul v-if="governance.reports?.length" class="item-list">
          <li v-for="report in latest(governance.reports, 5)" :key="report.id">
            <strong>{{ report.title }}</strong>
            <p>{{ report.summary || '暂无汇报摘要' }}</p>
            <p v-if="report.artifact_path" class="item-meta">{{ report.artifact_path }}</p>
          </li>
        </ul>
        <p v-else class="empty-copy">暂无项目汇报。</p>
      </section>
    </div>

    <section class="overview-card">
      <div class="card-heading">
        <h2>最近议题反馈</h2>
        <a-button type="link" @click="openList('feedback', '议题反馈')">更多</a-button>
      </div>
      <ul class="item-list">
        <li v-for="item in overview.feedback?.items || []" :key="item.id">
          <RouterLink :to="item.url">{{ item.summary }}</RouterLink>
          <p>
            议题修订 {{ item.topic_revision }} · {{ item.created_at }} ·
            <RouterLink :to="item.result_url">查看来源结果</RouterLink>
          </p>
        </li>
      </ul>
      <p v-if="!overview.feedback?.items?.length" class="empty-copy">
        暂无议题反馈；蓝图复盘保留在正文中。
      </p>
      <a-button type="link" @click="openList('historical_exceptions', '历史执行异常')"
        >历史执行异常（{{ overview.historical_exceptions?.total || 0 }}）</a-button
      >
    </section>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { displayBlueprintName } from '@/utils/blueprintName'
import { formatDateTime } from '@/utils/time'
import { ArrowUpRight, BookOpen, ScrollText } from '@lucide/vue'
import ProjectGovernanceGraph from '@/components/project/ProjectGovernanceGraph.vue'
import {
  governanceStatusLabel,
  overviewStatusLabel,
  topicAdmissionLabel,
  describeBoardError
} from '@/utils/governanceBoard'
import { governanceBoardApi } from '@/apis/governance_board_api'

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
const overview = computed(() => props.board.overview || {})
const effectiveDecisions = computed(() =>
  (governance.value.decisions || []).filter((item) => item.status === 'approved')
)
const groups = computed(() => {
  const data = overview.value
  const counts = data.pending?.counts || {}
  const states = data.work?.status_counts || {}
  return [
    {
      key: 'pending',
      title: '待处理',
      count: `${data.pending?.total || 0} 条`,
      note: `议题 ${counts.pending_topics || 0} · 工作建议 ${counts.pending_tasks || 0} · 草稿决策 ${counts.pending_decisions || 0}`
    },
    {
      key: 'work',
      title: '工作进展',
      count: `${data.work?.total || 0} 项工作`,
      note: `待办 ${states.todo || 0} · 进行中 ${states.in_progress || 0} · 受阻 ${states.blocked || 0} · 已完成 ${states.done || 0} · 已取消 ${states.cancelled || 0} · 逾期 ${data.work?.overdue_count || 0}`
    },
    {
      key: 'results',
      title: '待验收',
      count: `${data.results?.total || 0} 份结果，${data.results?.work_count || 0} 项工作`,
      note: '执行成功与人工接受、工作完成分别记录。'
    },
    {
      key: 'exceptions',
      title: '执行异常',
      count: `${data.exceptions?.total || 0} 条`,
      note: '最新尝试失败或中断；历史异常单独保留，不代表业务受阻。'
    }
  ].map((group) => ({ ...group, items: data[group.key]?.items || [] }))
})
const itemLabel = (item) =>
  `${item.kind ? ({ topic: '议题', suggestion: '工作建议', decision: '草稿决策', execution: '智能体尝试', delegation: '外部委派' }[item.kind] || item.kind) + ' · ' : ''}${item.number ? item.number + ' · ' : ''}${(item.kind ? item.title : item.summary) || item.title || item.summary || '议题反馈'}`
const detailLabel = (item) =>
  [
    item.kind === 'topic' ? topicAdmissionLabel(item.admission_status) : overviewStatusLabel(
      ['failed', 'interrupted'].includes(item.remote_status) ? item.remote_status : item.status
    ),
    item.remote_status && `本地${overviewStatusLabel(item.status)}`,
    item.overdue && '逾期',
    item.due_date && `截止 ${item.due_date}`,
    item.criteria_revision != null && `要求修订 ${item.criteria_revision}`,
    item.created_at && formatDateTime(item.created_at),
    item.error_message || item.error_code
  ]
    .filter(Boolean)
    .join(' · ')
const listOpen = ref(false),
  listTitle = ref(''),
  listSection = ref(''),
  listOffset = ref(0)
const listLoading = ref(false),
  listError = ref(''),
  listPage = ref({ total: 0, items: [] })
let listSeq = 0
/** 分页读取沿用卡片口径，关闭或切换项目后忽略迟到响应。 */
async function loadList(offset = 0) {
  const seq = ++listSeq,
    project = props.projectId,
    section = listSection.value
  listLoading.value = true
  listError.value = ''
  listOffset.value = offset
  try {
    const page = await governanceBoardApi.getOverviewPage(project, section, offset)
    if (seq === listSeq && project === props.projectId && listOpen.value) listPage.value = page
  } catch (error) {
    if (seq === listSeq && project === props.projectId && listOpen.value)
      listError.value = describeBoardError(error)
  } finally {
    if (seq === listSeq) listLoading.value = false
  }
}
function openList(section, title) {
  listSection.value = section
  listTitle.value = title
  listOpen.value = true
  loadList()
}
function closeList() {
  listOpen.value = false
  listSeq += 1
  listLoading.value = false
}
watch(() => props.projectId, closeList)
const workbenchRoute = computed(() => ({
  name: 'ProjectInspectionBoardComp',
  params: { project_id: props.projectId }
}))
const workbenchRecord = (query) => ({ ...workbenchRoute.value, query })
const workbenchAnchor = (anchor) => ({ ...workbenchRoute.value, hash: `#${anchor}` })
/** 治理列表由后端按创建顺序返回，保留最新记录供概览回顾。 */
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
.primary-link:visited,
.primary-link:active {
  color: var(--gray-0);
  background: var(--main-color);
}
.primary-link:hover {
  color: var(--gray-0);
  background: var(--main-600);
}
.default-dashboard a,
.default-dashboard a:visited,
.default-dashboard a:hover,
.default-dashboard a:active {
  text-decoration: none;
}
.card-heading a,
.card-heading a:visited,
.card-heading a:hover,
.card-heading a:active,
.empty-block a,
.empty-block a:visited,
.empty-block a:hover,
.empty-block a:active {
  color: var(--main-color);
}
.overview-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.summary-count {
  font-size: 20px;
  color: var(--gray-1000);
  font-weight: 600;
  margin: 0;
}
.summary-group {
  padding: 16px;
}
.item-list a,
.item-list a:visited {
  color: var(--main-color);
  text-decoration: none;
}
.item-list a:hover {
  text-decoration: underline;
}
.summary-group .item-list a {
  display: block;
  overflow-wrap: anywhere;
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
.decision-summary-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.decision-summary-item {
  min-width: 0;
  padding: 14px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-25);
}
.decision-summary-item header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}
.decision-summary-item header strong {
  color: var(--gray-1000);
  overflow-wrap: anywhere;
}
.decision-summary-item header span {
  flex: 0 0 auto;
  color: var(--gray-500);
  font-size: 12px;
}
.decision-summary-item :deep(.yk-markdown-preview) {
  max-height: 112px;
  overflow: hidden;
  color: var(--gray-700);
  line-height: 1.6;
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
  overflow-wrap: anywhere;
}
.blueprint-content :deep(a),
.blueprint-content :deep(a:visited),
.blueprint-content :deep(a:hover),
.blueprint-content :deep(a:active) {
  color: var(--main-color);
  text-decoration: none;
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
  .decision-summary-list {
    grid-template-columns: 1fr;
  }
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
  .overview-stats {
    grid-template-columns: 1fr;
  }
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
