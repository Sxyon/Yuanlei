<template>
  <section class="relations-card">
    <header class="relations-heading">
      <div>
        <p class="eyebrow">02 / GOVERNANCE MAP</p>
        <h2><Workflow :size="18" /> 议题、决策与任务</h2>
        <p>节点关系来自项目议题、决策和任务的实际关联。</p>
      </div>
      <RouterLink :to="workbenchRoute">打开项目工作台 <ArrowUpRight :size="14" /></RouterLink>
    </header>

    <p v-if="!nodes.length" class="graph-empty">
      提出议题、记录决策或创建任务后，关系图会在这里展示。
    </p>
    <div v-else class="graph-scroll" role="group" aria-label="项目议题、决策和任务关系图">
      <svg
        class="governance-graph"
        :viewBox="`0 0 ${graphWidth} ${graphHeight}`"
        :style="{ minWidth: `${graphWidth}px` }"
        role="group"
        aria-labelledby="governance-graph-title governance-graph-description"
      >
        <title id="governance-graph-title">项目治理关系图</title>
        <desc id="governance-graph-description">
          按议题、决策和任务分列显示，连线表示数据中已保存的关联。
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
          <tspan>{{ column.nodes.length }}</tspan>
        </text>
        <path
          v-for="edge in edges"
          :key="edge.key"
          class="graph-edge"
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
          :aria-label="`${node.kindLabel}：${node.item.title}，${node.kind === 'topic' ? `${topicAdmissionLabel(node.item.admission_status)} · ${topicProgressLabel(node.item.progress)}` : governanceStatusLabel(node.item.status)}`"
          :aria-pressed="selectedKey === node.key"
          @click="selectedKey = node.key"
          @keydown.enter.prevent="selectedKey = node.key"
          @keydown.space.prevent="selectedKey = node.key"
        >
          <title>{{ node.kindLabel }}：{{ node.item.title }}</title>
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
                : governanceStatusLabel(node.item.status)
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
      </svg>
    </div>
    <p v-if="hasMore" class="graph-note">
      图中每类最多显示最近 {{ maxPerKind }} 条；工作台可查看全部记录。
    </p>
    <div v-if="selectedNode" class="node-detail">
      <div class="node-detail-heading">
        <div>
          <p class="eyebrow">
            {{ selectedNode.kindLabel }} ·
            {{
              selectedNode.kind === 'topic'
                ? `${topicAdmissionLabel(selectedNode.item.admission_status)} · ${topicProgressLabel(selectedNode.item.progress)}`
                : governanceStatusLabel(selectedNode.item.status)
            }}
          </p>
          <h3>{{ selectedNode.item.title }}</h3>
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
      <MarkdownPreview v-if="selectedBody" :content="selectedBody" compact />
      <p v-else class="node-detail-empty">这条记录还没有补充说明。</p>
      <p v-if="selectedRelations.length" class="node-relations">
        关联：<button
          v-for="relation in selectedRelations"
          :key="relation.key"
          type="button"
          @click="selectedKey = relation.key"
        >
          {{ relation.kindLabel }} · {{ relation.item.title }}
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
  governanceStatusLabel,
  topicAdmissionLabel,
  topicProgressLabel
} from '@/utils/governanceBoard'

const props = defineProps({
  projectId: { type: String, required: true },
  governance: { type: Object, default: () => ({}) }
})

const router = useRouter()
const maxPerKind = 10
const graphWidth = 1040
const nodeWidth = 292
const nodeHeight = 78
const columnX = { topic: 18, decision: 374, task: 730 }
const workbenchRoute = computed(() => ({
  name: 'ProjectInspectionBoardComp',
  params: { project_id: props.projectId }
}))
const columns = computed(() => [
  {
    key: 'topic',
    title: '议题',
    x: columnX.topic,
    nodes: latest(props.governance.topics, 'topic')
  },
  {
    key: 'decision',
    title: '决策',
    x: columnX.decision,
    nodes: latest(props.governance.decisions, 'decision')
  },
  {
    key: 'task',
    title: '任务',
    x: columnX.task,
    nodes: latest(props.governance.tasks, 'task')
  }
])

function latest(items, kind) {
  return (items || [])
    .slice(-maxPerKind)
    .reverse()
    .map((item, index) => ({
      key: `${kind}:${item.id}`,
      kind,
      kindLabel: { topic: '议题', decision: '决策', task: '任务' }[kind],
      item,
      x: columnX[kind],
      y: 57 + index * 96,
      lines: wrapTitle(item.title)
    }))
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
const hasMore = computed(() =>
  ['topics', 'decisions', 'tasks'].some((key) => (props.governance[key] || []).length > maxPerKind)
)
const selectedBody = computed(() => {
  const item = selectedNode.value?.item
  if (!item) return ''
  if (selectedNode.value.kind === 'topic') return item.summary || ''
  if (selectedNode.value.kind === 'decision')
    return [item.conclusion, item.rationale && `\n\n---\n\n**决策理由**\n\n${item.rationale}`]
      .filter(Boolean)
      .join('')
  return item.description || ''
})

const edges = computed(() => {
  const result = []
  const addEdge = (from, to) => {
    const source = nodeMap.value.get(from)
    const target = nodeMap.value.get(to)
    if (!source || !target) return
    const startX = source.x + nodeWidth
    const startY = source.y + nodeHeight / 2
    const endX = target.x - 4
    const endY = target.y + nodeHeight / 2
    const curve = Math.max(36, (endX - startX) * 0.45)
    result.push({
      key: `${from}->${to}`,
      path: `M ${startX} ${startY} C ${startX + curve} ${startY}, ${endX - curve} ${endY}, ${endX} ${endY}`
    })
  }
  for (const decision of props.governance.decisions || []) {
    if (decision.topic_id) addEdge(`topic:${decision.topic_id}`, `decision:${decision.id}`)
  }
  for (const task of props.governance.tasks || []) {
    if (task.topic_id) addEdge(`topic:${task.topic_id}`, `task:${task.id}`)
    if (task.decision_id) addEdge(`decision:${task.decision_id}`, `task:${task.id}`)
  }
  return result
})

const selectedRelations = computed(() => {
  const node = selectedNode.value
  if (!node) return []
  const item = node.item
  if (node.kind === 'topic') {
    const linkedDecisionIds = new Set(
      nodes.value
        .filter((candidate) => candidate.kind === 'decision' && candidate.item.topic_id === item.id)
        .map((candidate) => candidate.item.id)
    )
    return nodes.value.filter(
      (candidate) =>
        (candidate.kind === 'decision' && candidate.item.topic_id === item.id) ||
        (candidate.kind === 'task' &&
          (item.id === candidate.item.topic_id ||
            linkedDecisionIds.has(candidate.item.decision_id)))
    )
  }
  if (node.kind === 'decision') {
    const topic = nodes.value.find(
      (candidate) => candidate.kind === 'topic' && candidate.item.id === item.topic_id
    )
    const tasks = nodes.value.filter(
      (candidate) => candidate.kind === 'task' && candidate.item.decision_id === item.id
    )
    return [...(topic ? [topic] : []), ...tasks]
  }
  const topic = nodes.value.find(
    (candidate) => candidate.kind === 'topic' && candidate.item.id === item.topic_id
  )
  const decision = nodes.value.find(
    (candidate) => candidate.kind === 'decision' && candidate.item.id === item.decision_id
  )
  return [topic, decision].filter(Boolean)
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
  if (node.kind === 'task') {
    const decision = (props.governance.decisions || []).find(
      (candidate) => candidate.id === node.item.decision_id
    )
    to.hash = '#tasks'
    to.query = {
      task_id: node.item.id,
      topic_id: node.item.topic_id || decision?.topic_id || undefined
    }
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
  fill: #2563eb;
}
.is-decision .node-kind {
  fill: #7c3aed;
}
.is-task .node-kind {
  fill: #0f766e;
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
  fill: #d97706;
}
.status-dot.status-canonical,
.status-dot.status-approved {
  fill: #059669;
}
.status-dot.status-rejected,
.status-dot.status-revoked {
  fill: #dc2626;
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
