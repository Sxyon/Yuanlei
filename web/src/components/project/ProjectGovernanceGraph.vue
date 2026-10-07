<template>
  <section class="relations-card">
    <header class="relations-heading">
      <div>
        <p class="eyebrow">02 / GOVERNANCE MAP</p>
        <h2><Workflow :size="18" /> 议题、决策、正式工作与结果</h2>
        <p>
          实线为当前来源及结果归属；虚线“反馈”为已确认的议题反馈。历史冻结依据由当次执行入口查看。
        </p>
      </div>
      <RouterLink :to="workbenchRoute">打开项目工作台 <ArrowUpRight :size="14" /></RouterLink>
    </header>

    <p v-if="!nodes.length" class="graph-empty">
      提出议题、记录决策或创建正式工作后，关系图会在这里展示。
    </p>
    <div v-else class="graph-scroll" role="group" aria-label="项目议题、决策、正式工作与业务结果关系图">
      <svg
        class="governance-graph"
        :viewBox="`0 0 ${graphWidth} ${graphHeight}`"
        :style="{ minWidth: `${graphWidth}px` }"
        role="group"
        aria-labelledby="governance-graph-title governance-graph-description"
      >
        <title id="governance-graph-title">项目治理关系图</title>
        <desc id="governance-graph-description">
          按议题、决策、正式工作和结果分列显示，连线表示数据中已保存的关联。
        </desc>
        <defs>
          <marker
            id="governance-arrow"
            markerWidth="8"
            markerHeight="8"
            refX="7"
            refY="4"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 Z" />
          </marker>
        </defs>
        <text v-for="column in columns" :key="column.key" class="column-label" :x="column.x" y="35">
          {{ column.title }}
          <tspan>{{ column.nodes.length }} / {{ column.total }}</tspan>
        </text>
        <path
          v-for="edge in edges"
          :key="edge.key"
          class="graph-edge"
          :class="{ feedback: edge.label === '反馈' }"
          :d="edge.path"
          marker-end="url(#governance-arrow)"
        />
        <g v-for="column in columns" :key="`${column.key}-empty`">
          <text
            v-if="!column.nodes.length"
            class="column-empty"
            :x="column.x + nodeWidth / 2"
            y="102"
          >
            暂无{{ column.title }}
          </text>
        </g>
        <g
          v-for="node in nodes"
          :key="node.key"
          class="graph-node"
          :class="[`is-${node.kind}`, { selected: selectedKey === node.key }]"
          :transform="`translate(${node.x} ${node.y})`"
          role="button"
          tabindex="0"
          :aria-label="`${node.kindLabel}：${nodeTitle(node)}，${node.kind === 'topic' ? `${topicAdmissionLabel(node.item.admission_status)} · ${topicProgressLabel(node.item.progress)}` : overviewStatusLabel(node.item.status)}`"
          :aria-pressed="selectedKey === node.key"
          @click="selectedKey = node.key"
          @keydown.enter.prevent="selectedKey = node.key"
          @keydown.space.prevent="selectedKey = node.key"
        >
          <title>{{ node.kindLabel }}：{{ nodeTitle(node) }}</title>
          <rect class="node-card" :width="nodeWidth" :height="nodeHeight" rx="9" />
          <circle
            class="status-dot"
            cx="16"
            cy="18"
            r="4"
            :class="`status-${node.item.admission_status || node.item.status}`"
          />
          <text class="node-kind" x="28" y="22">
            {{ node.kindLabel }} ·
            {{
              node.kind === 'topic'
                ? `${topicAdmissionLabel(node.item.admission_status)} · ${topicProgressLabel(node.item.progress)}`
                : overviewStatusLabel(node.item.status)
            }}
          </text>
          <text
            v-for="(line, index) in node.lines"
            :key="index"
            class="node-title"
            x="14"
            :y="48 + index * 17"
          >
            {{ line }}
          </text>
        </g>
        <text
          v-for="edge in edges.filter((item) => item.label === '反馈')"
          :key="`${edge.key}-label`"
          class="column-empty"
          :x="edge.labelX"
          :y="edge.labelY"
        >
          反馈
        </text>
      </svg>
    </div>
    <p v-if="hasMore" class="graph-note">
      每类最多 {{ maxPerKind }} 条；{{
        omittedSummary
      }}。未展示节点不画边，可通过下方来源或当次依据入口查看。
    </p>
    <div v-if="selectedNode" class="node-detail">
      <div class="node-detail-heading">
        <div>
          <p class="eyebrow">
            {{ selectedNode.kindLabel }} ·
            {{
              selectedNode.kind === 'topic'
                ? `${topicAdmissionLabel(selectedNode.item.admission_status)} · ${topicProgressLabel(selectedNode.item.progress)}`
                : overviewStatusLabel(selectedNode.item.status)
            }}
          </p>
          <h3>{{ nodeTitle(selectedNode) }}</h3>
        </div>
        <a-button type="primary" @click="openSelectedInWorkbench">在工作台查看</a-button>
      </div>
      <a-alert
        v-if="
          selectedNode?.item?.topic_execution_hint === 'pause_recommended' ||
          selectedNode?.item?.execution_hint === 'pause_recommended'
        "
        type="warning"
        show-icon
        message="议题建议暂停原方案"
        description="仅为议题提示，不撤销决策或暂停任务或执行记录。"
      />
      <p
        v-if="selectedNode.kind === 'decision' && selectedNode.item.topic_id"
        class="node-relations"
      >
        <RouterLink :to="recordLink({ topic_id: selectedNode.item.topic_id })"
          >关联议题（可含归档或图外记录）</RouterLink
        >
      </p>
      <p v-if="selectedNode.kind === 'work'" class="node-relations">
        当前来源：
        <RouterLink
          v-if="selectedNode.item.topic_id"
          :to="recordLink({ topic_id: selectedNode.item.topic_id })"
          >议题（可含图外记录）</RouterLink
        >
        <RouterLink
          v-if="selectedNode.item.source_decision_id"
          :to="recordLink({ decision_id: selectedNode.item.source_decision_id })"
          >决策修订 {{ selectedNode.item.source_decision_revision }} · 查看历史</RouterLink
        >
        <span v-if="!selectedNode.item.topic_id && !selectedNode.item.source_decision_id"
          >独立工作</span
        >
      </p>
      <p v-if="selectedNode.kind === 'result'" class="node-relations">
        <RouterLink :to="selectedNode.item.url"
          >来源工作 {{ selectedNode.item.number }} · 结果
          {{ overviewStatusLabel(selectedNode.item.status) }}</RouterLink
        >
        <span>当次要求修订 {{ selectedNode.item.criteria_revision ?? '未知' }}</span>
        <span v-if="selectedNode.item.frozen_decision_id"
          >冻结决策修订 {{ selectedNode.item.frozen_decision_revision }}</span
        >
        <RouterLink v-if="selectedNode.item.history_url" :to="selectedNode.item.history_url"
          >查看当次执行与历史依据</RouterLink
        >
        <span v-else>人工结果，无执行尝试</span>
        <RouterLink
          v-for="feedback in selectedFeedbacks"
          :key="feedback.id"
          :to="recordLink({ topic_id: feedback.topic_id })"
          >反馈议题 · 修订 {{ feedback.topic_revision }}</RouterLink
        >
      </p>
      <MarkdownPreview v-if="selectedBody" :content="selectedBody" compact />
      <p v-else class="node-detail-empty">这条记录还没有补充说明。</p>
      <p v-if="selectedRelations.length" class="node-relations">
        关联：<button
          v-for="relation in selectedRelations"
          :key="relation.key"
          type="button"
          @click="selectedKey = relation.key"
        >
          {{ relation.kindLabel }} · {{ nodeTitle(relation) }}
        </button>
      </p>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { ArrowUpRight, Workflow } from '@lucide/vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import {
  overviewStatusLabel,
  topicAdmissionLabel,
  topicProgressLabel
} from '@/utils/governanceBoard'

const props = defineProps({
  projectId: { type: String, required: true },
  governance: { type: Object, default: () => ({}) },
  graph: { type: Object, default: () => ({}) }
})

const router = useRouter()
const maxPerKind = 10
const graphWidth = 1360
const nodeWidth = 282
const nodeHeight = 78
const columnX = { topic: 18, decision: 362, work: 706, result: 1050 }
const workbenchRoute = computed(() => ({
  name: 'ProjectInspectionBoardComp',
  params: { project_id: props.projectId }
}))
const columns = computed(() =>
  [
    {
      key: 'topic',
      title: '议题',
      items: [...(props.governance.topics || [])].reverse(),
      total: (props.governance.topics || []).length
    },
    {
      key: 'decision',
      title: '决策',
      items: [...(props.governance.decisions || [])].reverse(),
      total: (props.governance.decisions || []).length
    },
    {
      key: 'work',
      title: '正式工作',
      items: props.graph.work?.items || [],
      total: props.graph.work?.total || 0
    },
    {
      key: 'result',
      title: '业务结果',
      items: props.graph.results?.items || [],
      total: props.graph.results?.total || 0
    }
  ].map((column) => ({
    ...column,
    x: columnX[column.key],
    nodes: column.items.slice(0, maxPerKind).map((item, index) => ({
      key: `${column.key}:${item.id}`,
      kind: column.key,
      kindLabel: column.title,
      item,
      x: columnX[column.key],
      y: 57 + index * 96,
      lines: wrapTitle(
        column.key === 'result'
          ? item.summary
          : `${item.number ? item.number + ' · ' : ''}${item.title || '未命名'}`
      )
    }))
  }))
)
const omittedSummary = computed(() =>
  columns.value
    .map((column) => `${column.title}遗漏 ${Math.max(0, column.total - column.nodes.length)} 条`)
    .join(' · ')
)
const recordLink = (query) => ({ ...workbenchRoute.value, query })
const selectedFeedbacks = computed(() =>
  (props.graph.feedback || []).filter((item) => item.result_id === selectedNode.value?.item.id)
)

/** 结果用摘要识别，其他节点使用自身标题。 */
function nodeTitle(node) {
  return node.kind === 'result' ? node.item.summary : node.item.title
}

function wrapTitle(title) {
  const chars = Array.from(String(title || '未命名'))
  const lines = [chars.slice(0, 24).join(''), chars.slice(24, 48).join('')]
  if (chars.length > 48) lines[1] = `${lines[1].slice(0, 22)}…`
  return lines.filter(Boolean)
}

const nodes = computed(() => columns.value.flatMap((column) => column.nodes))
const graphHeight = computed(() =>
  Math.max(166, ...columns.value.map((column) => 86 + column.nodes.length * 96))
)
const nodeMap = computed(() => new Map(nodes.value.map((node) => [node.key, node])))
const selectedKey = ref('')
const selectedNode = computed(() => nodeMap.value.get(selectedKey.value) || nodes.value[0] || null)
const hasMore = computed(() => columns.value.some((column) => column.total > column.nodes.length))
const selectedBody = computed(() => {
  const item = selectedNode.value?.item
  if (!item) return ''
  if (selectedNode.value.kind === 'topic') return item.summary || ''
  if (selectedNode.value.kind === 'decision')
    return [item.conclusion, item.rationale && `\n\n---\n\n**决策理由**\n\n${item.rationale}`]
      .filter(Boolean)
      .join('')
  return item.summary || item.description || ''
})

const edges = computed(() => {
  const result = []
  const add = (from, to, label) => {
    const source = nodeMap.value.get(from),
      target = nodeMap.value.get(to)
    if (!source || !target) return
    const forward = target.x > source.x
    const startX = source.x + (forward ? nodeWidth : 0),
      endX = target.x + (forward ? 0 : nodeWidth)
    const startY = source.y + nodeHeight / 2,
      endY = target.y + nodeHeight / 2
    const curve = forward ? 36 : -36
    result.push({
      key: `${from}->${to}:${label}`,
      from,
      to,
      label,
      path: `M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`,
      labelX: (startX + endX) / 2,
      labelY: (startY + endY) / 2 - 8
    })
  }
  for (const item of props.governance.decisions || [])
    if (item.topic_id) add(`topic:${item.topic_id}`, `decision:${item.id}`, '议题关联')
  for (const item of props.graph.work?.items || []) {
    if (item.topic_id) add(`topic:${item.topic_id}`, `work:${item.id}`, '当前来源')
    if (item.source_decision_id)
      add(`decision:${item.source_decision_id}`, `work:${item.id}`, '当前来源')
  }
  for (const item of props.graph.results?.items || [])
    add(`work:${item.task_id}`, `result:${item.id}`, '结果归属')
  for (const item of props.graph.feedback || [])
    add(`result:${item.result_id}`, `topic:${item.topic_id}`, '反馈')
  return result
})
const selectedRelations = computed(() => {
  const key = selectedNode.value?.key
  return nodes.value.filter((node) =>
    edges.value.some(
      (edge) =>
        (edge.from === key && edge.to === node.key) || (edge.to === key && edge.from === node.key)
    )
  )
})

function openSelectedInWorkbench() {
  const node = selectedNode.value
  if (!node) return
  const to = { ...workbenchRoute.value, hash: '#topics', query: {} }
  if (node.kind === 'topic') to.query = { topic_id: node.item.id }
  if (node.kind === 'decision') {
    to.hash = '#decisions'
    to.query = { decision_id: node.item.id, topic_id: node.item.topic_id || undefined }
  }
  if (node.kind === 'work' || node.kind === 'result') {
    router.push(node.item.url)
    return
  }
  router.push(to)
}

watch(
  nodes,
  (current) => {
    if (!current.some((node) => node.key === selectedKey.value))
      selectedKey.value = current[0]?.key || ''
  },
  { immediate: true }
)
</script>

<style scoped lang="less">
.relations-card {
  min-width: 0;
  padding: 22px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-0);
}
.relations-heading,
.node-detail-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
}
.eyebrow {
  margin: 0 0 7px;
  color: var(--main-color);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}
.relations-heading h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: var(--gray-1000);
  font-size: 18px;
}
.relations-heading p:not(.eyebrow) {
  margin: 6px 0 0;
  color: var(--gray-500);
  font-size: 13px;
}
.relations-heading a {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--main-color);
  text-decoration: none;
  white-space: nowrap;
}
.relations-heading a:visited,
.relations-heading a:hover,
.relations-heading a:active {
  color: var(--main-color);
  text-decoration: none;
}
.graph-scroll {
  overflow-x: auto;
  margin: 18px -4px 0;
  padding: 4px;
}
.governance-graph {
  display: block;
  width: 100%;
  min-width: 1000px;
  height: auto;
  overflow: visible;
}
.column-label {
  fill: var(--gray-900);
  font-size: 15px;
  font-weight: 700;
}
.column-label tspan {
  fill: var(--gray-500);
  font-size: 12px;
  font-weight: 400;
}
.column-empty {
  fill: var(--gray-400);
  font-size: 13px;
  text-anchor: middle;
}
.graph-edge.feedback {
  stroke-dasharray: 5 4;
  stroke: var(--main-color);
}
.is-result .node-kind {
  fill: var(--main-color);
}
.graph-edge {
  fill: none;
  stroke: var(--gray-300);
  stroke-width: 1.5;
}
.graph-edge marker path {
  fill: var(--gray-400);
}
.graph-node {
  cursor: pointer;
  outline: none;
}
.node-card {
  fill: var(--gray-0);
  stroke: var(--gray-200);
  stroke-width: 1;
}
.graph-node:hover .node-card,
.graph-node:focus-visible .node-card,
.graph-node.selected .node-card {
  stroke: var(--main-color);
  stroke-width: 2;
}
.graph-node.selected .node-card {
  fill: var(--main-30);
}
.is-topic .node-kind {
  fill: var(--color-info-700);
}
.is-decision .node-kind {
  fill: var(--color-accent-700);
}
.is-work .node-kind {
  fill: var(--color-success-700);
}
.node-kind {
  font-size: 11px;
  font-weight: 600;
}
.node-title {
  fill: var(--gray-900);
  font-size: 12px;
  font-weight: 600;
}
.status-dot {
  fill: var(--color-warning-700);
}
.status-dot.status-canonical,
.status-dot.status-approved {
  fill: var(--color-success-700);
}
.status-dot.status-rejected,
.status-dot.status-revoked {
  fill: var(--color-error-700);
}
.status-dot.status-superseded {
  fill: var(--gray-500);
}
.graph-empty {
  margin: 18px 0 0;
  padding: 26px 18px;
  border-radius: 8px;
  background: var(--gray-25);
  color: var(--gray-500);
  text-align: center;
}
.graph-note {
  margin: 6px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}
.node-detail {
  display: grid;
  gap: 12px;
  margin-top: 15px;
  padding: 16px;
  border-top: 1px solid var(--gray-100);
  background: var(--gray-25);
}
.node-detail-heading h3 {
  margin: 0;
  color: var(--gray-1000);
  font-size: 16px;
  overflow-wrap: anywhere;
}
.node-detail .eyebrow {
  margin-bottom: 5px;
}
.node-detail-empty {
  margin: 0;
  color: var(--gray-500);
  font-size: 13px;
}
.node-relations {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0;
  color: var(--gray-500);
  font-size: 12px;
}
.node-relations button {
  padding: 3px 7px;
  border: 1px solid var(--gray-200);
  border-radius: 5px;
  background: var(--gray-0);
  color: var(--gray-700);
  cursor: pointer;
}
@media (max-width: 680px) {
  .relations-card {
    padding: 17px;
  }
  .relations-heading,
  .node-detail-heading {
    flex-direction: column;
  }
  .relations-heading a {
    margin-top: 4px;
  }
}
</style>
