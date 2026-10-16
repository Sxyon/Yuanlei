<script setup>
import { inject, computed, onBeforeUnmount, ref, watch } from 'vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { useRoute } from 'vue-router'
import { projectDashboardApi } from '@/apis/project_dashboard_api'
import { createDashboardSrcdoc } from '@/utils/dashboardFrame'
import { describeBoardError, overviewStatusLabel } from '@/utils/governanceBoard'
import { blueprintDocumentHeading, blueprintDocumentBody } from '@/utils/blueprintName'
import { useUserStore } from '@/stores/user'
import ThemedOverview from './ThemedOverview.vue'
import ProjectGitAttentionSummary from '@/components/ProjectGitAttentionSummary.vue'
const accessLost = inject('projectAccessLost', () => {})
const props = defineProps({ projectId: { type: String, required: true } })
const themeContext = inject('projectThemeContext', null)
const presentation = computed(() => themeContext?.value?.package?.theme.presentation || 'baseline')
const researchTopics = ref([]), decisions = ref([]), blueprintCount = ref(0)
const route = useRoute()
const user = useUserStore(),
  board = ref({}),
  blueprint = ref(null),
  error = ref(''),
  loading = ref(false),
  activity = ref([]),
  business = ref(null),
  businessError = ref(''),
  showBusiness = ref(false),
  more = ref(null),
  moreRows = ref({}),
  moreLoading = ref(false)
let generation = 0,
  moreSequence = 0
const capture = () => ({ project: props.projectId, user: user.uid, generation })
const current = (value) =>
  value.project === props.projectId && value.user === user.uid && value.generation === generation
const overview = computed(() => board.value.overview || {})
const groups = computed(() =>
  [
    { key: 'results', title: '待验收', note: '结果接受与工作完成分别办理' },
    { key: 'exceptions', title: '执行异常', note: '以准确工作中的当前尝试为准' },
    { key: 'work', title: '工作进展', note: '当前工作状态' },
    { key: 'pending', title: '待处理', note: '议题、计划与草案' }
  ].map((item) => ({ ...item, ...overview.value[item.key] }))
)
const attentionGroups = computed(() => groups.value.filter(item => ['results', 'pending', 'exceptions'].includes(item.key)))
const attentionRows = computed(() => attentionGroups.value.flatMap(group => (group.items || []).slice(0, 3).map(item => ({ ...item, group: group.key }))))
const progressCounts = computed(() => [
  { value: overview.value.work?.status_counts?.in_progress || 0, label: '进行中', key: 'work' },
  { value: overview.value.pending?.total || 0, label: '待判断', key: 'pending' },
  { value: overview.value.work?.blocked_count || 0, label: '阻塞', key: 'exceptions' }
])
const activityTime = (raw) => raw ? new Date(raw).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const clip = (text, max) => {
  const chars = Array.from(String(text || ''))
  return chars.length > max ? chars.slice(0, max - 1).join('') + '…' : chars.join('')
}
const blueprintSummary = computed(() =>
  blueprint.value
    ? {
        title: clip(blueprintDocumentHeading(blueprint.value.name, blueprint.value.content), 32),
        content: clip(blueprintDocumentBody(blueprint.value.content).replace(/[#*`>]|\[|\]/g, ''), 100),
        source: clip(blueprint.value.name, 24)
      }
    : null
)
function objectLink(item) {
  if (item.kind === 'suggestion')
    return {
      name: 'ProjectPlans',
      params: { project_id: props.projectId },
      query: { task_id: item.id }
    }
  if (item.kind === 'topic')
    return {
      name: 'ProjectTopics',
      params: { project_id: props.projectId },
      query: { topic_id: item.id }
    }
  if (item.kind === 'decision')
    return {
      name: 'ProjectTopics',
      params: { project_id: props.projectId },
      query: { decision_id: item.id, ...(item.topic_id ? { topic_id: item.topic_id } : {}) }
    }
  return item.url
}
function topicLink(item) {
  return {
    name: 'ProjectTopics',
    params: { project_id: props.projectId },
    query: {
      ...(item.kind === 'decision'
        ? item.topic_id
          ? { topic_id: item.topic_id }
          : {}
        : { topic_id: item.topic_id || item.id }),
      ...(item.kind === 'decision'
        ? { decision_id: item.id }
        : item.kind === 'comment'
          ? { comment_id: item.comment_id || item.id }
          : {})
    }
  }
}
function failure(cause) {
  error.value = describeBoardError(cause)
  if ([401, 403, 404].includes(cause?.status || cause?.response?.status)) {
    board.value = {}
    blueprint.value = null
    activity.value = []
    researchTopics.value = []
    decisions.value = []
    business.value = null
    more.value = null
    moreRows.value = {}
    showBusiness.value = false
    generation++
    loading.value = false
    accessLost()
  }
}
async function load() {
  generation++
  const token = capture()
  loading.value = true
  error.value = ''
  const results = await Promise.allSettled([
    presentation.value === 'baseline' ? api.getProjectBoard(token.project) : Promise.resolve({}),
    api.listBlueprints(token.project),
    api.listTopics(token.project, false),
    api.recentActivity(token.project),
    presentation.value === 'research' ? api.listDecisions(token.project) : Promise.resolve([])
  ])
  if (!current(token)) return
  for (const result of results)
    if (result.status === 'rejected') {
      failure(result.reason)
      if (!current(token)) return
    }
  if (results[0].status === 'fulfilled') board.value = results[0].value
  if (results[2].status === 'fulfilled') researchTopics.value = results[2].value
  if (results[4].status === 'fulfilled') decisions.value = results[4].value
  if (results[3].status === 'fulfilled') activity.value = results[3].value.items
  if (results[1].status === 'fulfilled') {
    blueprintCount.value = results[1].value.documents?.length || 0
    const document = results[1].value.documents?.[0]
    blueprint.value = null
    if (document)
      try {
        const text = await api.getBlueprint(token.project, document.name)
        if (current(token)) blueprint.value = text
      } catch (cause) {
        if (current(token)) {
          error.value = describeBoardError(cause)
          if ([401, 403].includes(cause?.status || cause?.response?.status)) failure(cause)
        }
      }
  }
  if (current(token)) loading.value = false
}
function closeMore() { more.value = null; moreSequence++ }
async function openMore(group, offset = 0) {
  const token = capture(),
    request = ++moreSequence
  const active = () => current(token) && request === moreSequence && more.value?.key === group.key
  more.value = group
  moreRows.value = {}
  moreLoading.value = true
  try {
    const result = await api.getOverviewPage(token.project, group.key, offset, 20)
    if (active()) moreRows.value = result
  } catch (cause) {
    if (active()) failure(cause)
  } finally {
    if (active()) moreLoading.value = false
  }
}
async function readBusiness() {
  showBusiness.value = !showBusiness.value
  if (!showBusiness.value) return
  const token = capture()
  businessError.value = ''
  try {
    const value = await projectDashboardApi.getDashboard(token.project)
    if (current(token)) business.value = value
  } catch (cause) {
    if (current(token)) {
      businessError.value = describeBoardError(cause)
      if ([401, 403, 404].includes(cause?.status || cause?.response?.status)) failure(cause)
    }
  }
}
watch(
  () => [props.projectId, user.uid, themeContext?.value?.scope],
  () => {
    generation++
    board.value = {}
    blueprint.value = null
    activity.value = []
    researchTopics.value = []
    decisions.value = []
    business.value = null
    more.value = null
    void load()
    if (presentation.value === 'baseline' && route.query.view === 'business') {
      showBusiness.value = false
      void readBusiness()
    }
  },
  { immediate: true }
)
onBeforeUnmount(() => generation++)
</script>
<template>
  <section class="overview-workspace" aria-label="项目总览">
    <div v-if="presentation === 'baseline'" class="overview-tools"><details class="overview-more"><summary aria-label="概览更多操作">···</summary><div><button @click="readBusiness">业务大屏</button><button :disabled="loading" @click="load">刷新</button></div></details></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <p v-if="loading" role="status">正在读取项目事实…</p>
    <div v-if="showBusiness && presentation === 'baseline'" class="business-display">
      <a-alert v-if="businessError" type="error" :message="businessError" />
      <iframe v-else-if="business?.state === 'ready'" :srcdoc="createDashboardSrcdoc(business.html)" sandbox referrerpolicy="no-referrer" title="项目静态业务大屏" />
      <p v-else>尚无可用业务大屏。可在平台项目对话中维护静态页面。</p>
      <RouterLink :to="{ name: 'AgentComp', query: { project_id: projectId } }">前往平台项目对话</RouterLink>
    </div>
    <ThemedOverview v-if="presentation !== 'baseline'" :presentation="presentation" :project-id="projectId" :blueprint="blueprint" :topics="researchTopics" :decisions="decisions" :activity="activity" :loading="loading" />
    <div v-else class="overview-columns" data-overview-presentation="baseline">
      <div class="overview-stack overview-primary"><ProjectGitAttentionSummary :project-id="projectId" section="approvals" />
        <section class="overview-panel attention-panel">
          <header><h2>需要你处理</h2><details v-if="attentionGroups.some(group => group.total)" class="overview-more"><summary aria-label="查看全部待处理事项">···</summary><div><button v-for="group in attentionGroups" :key="group.key" @click="openMore(group)">{{ group.title }} · {{ group.total || 0 }}</button></div></details></header>
          <article v-for="item in attentionRows" :key="`${item.group}:${item.id}`" class="attention-row">
            <RouterLink class="object-target" :to="objectLink(item)"><strong>{{ item.title || item.task_title || item.summary || '交付结果' }}</strong><p>{{ clip(item.description || item.summary || item.conclusion || item.error_message, 120) }}</p></RouterLink>
            <span class="workspace-status" :class="{ warning: item.group === 'exceptions' }">{{ item.group === 'results' ? '待验收' : item.group === 'exceptions' ? '阻塞' : overviewStatusLabel(item.status) }}</span>
          </article>
          <p v-if="!attentionRows.length && !loading" class="metadata">暂无需要处理的事项。</p>
        </section>
        <section class="overview-panel progress-panel"><header><h2>当前推进</h2><button class="quiet" @click="openMore(groups.find(group => group.key === 'work'))" aria-label="查看全部工作">···</button></header>
          <div class="progress-summary"><button v-for="item in progressCounts" :key="item.key" @click="openMore(groups.find(group => group.key === item.key))"><strong>{{ item.value }}</strong><span>{{ item.label }}</span></button></div>
        </section>
      </div>
      <div class="overview-stack overview-secondary">
        <section class="overview-panel blueprint-preview">
          <RouterLink v-if="blueprintSummary" class="object-target" :to="{ name: 'ProjectBlueprints', params: { project_id: projectId }, query: { blueprint: blueprint.name } }"><h2>{{ blueprintSummary.title }}</h2><p>{{ blueprintSummary.content }}</p></RouterLink>
          <p v-else-if="!loading" class="metadata">暂无蓝图，可从项目蓝图开始记录目标。</p>
          <footer v-if="blueprintSummary && blueprintCount > 1">— {{ blueprintSummary.source }}</footer>
        </section>
        <section class="overview-panel recent-activity"><header><h2>最近动态</h2></header>
          <RouterLink v-for="item in activity" :key="item.event_key" class="recent-item object-target" :to="topicLink(item)"><span class="recent-kind">{{ { decision: '决策', comment: '讨论', topic: '议题' }[item.kind] }}</span><strong>{{ clip(item.title, 44) }}</strong><time :title="`${item.author_name || ''} · ${item.created_at}`">{{ activityTime(item.created_at) }}</time></RouterLink>
          <p v-if="!activity.length && !loading" class="metadata">暂无动态</p>
        </section>
        <ProjectGitAttentionSummary :project-id="projectId" section="occupancies" />
      </div>
    </div>
    <a-modal :open="!!more" :title="more?.title" :footer="null" :width="720" @cancel="closeMore"><a-spin v-if="moreLoading" />
      <article v-for="item in moreRows.items || []" :key="item.id" class="more-row"><RouterLink :to="objectLink(item)" @click="closeMore">{{ item.title || item.task_title || item.summary }}</RouterLink><p>{{ item.description || item.error_message }}</p></article>
      <a-pagination :current="Math.floor((moreRows.offset || 0) / 20) + 1" :total="moreRows.total || 0" :page-size="20" :show-size-changer="false" @change="(page) => openMore(more, (page - 1) * 20)" />
    </a-modal>
  </section>
</template>
<style scoped lang="less">
.overview-workspace { color: var(--color-text); padding-top:24px; }
.overview-tools { display:flex; justify-content:flex-end; height:0; position:relative; top:-22px; }
.overview-columns { display:grid; grid-template-columns:minmax(0,1.75fr) minmax(245px,1fr); gap:24px; align-items:start; }
.overview-stack { display:grid; gap:20px; min-width:0; }
.overview-panel { background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; padding:24px; min-width:0; > header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:18px; } h2 { font-size:19px; font-weight:650; line-height:1.55; margin:0; } }
.attention-row { display:flex; align-items:center; gap:14px; padding:16px 0; border-bottom:1px solid var(--gray-150); &:last-child { border:0; } a { flex:1; min-width:0; } strong { font-size:15px; font-weight:600; } p { font-size:13px; line-height:1.65; margin:5px 0 0; color:var(--color-text-secondary); } }
.workspace-status { display:inline-block; padding:3px 8px; border-radius:5px; font-size:11px; background:var(--main-10); color:var(--main-color); flex-shrink:0; }.warning { color:var(--color-warning-700); background:var(--color-warning-50); }
.progress-summary { display:flex; gap:32px; margin:20px 0; button { background:none; border:0; padding:0; color:var(--color-text-secondary); cursor:pointer; font-size:13px; text-align:left; } strong { display:block; font-size:22px; color:var(--color-text); } }
.blueprint-preview { p { font-size:14px; line-height:1.8; color:var(--color-text-secondary); margin:16px 0; } footer { text-align:right; font-size:12px; color:var(--color-text-secondary); } }
.object-target { color:var(--color-text); text-decoration:none; overflow-wrap:anywhere; display:block; &:hover strong, &:hover h2 { color:var(--main-color); } &:focus-visible { outline:2px solid var(--main-color); outline-offset:4px; } }
.recent-item { display:grid; grid-template-columns:34px minmax(0,1fr) auto; gap:10px; align-items:start; padding:15px 0; border-bottom:1px solid var(--gray-150); &:last-child { border:0; } strong { font-size:14px; font-weight:500; } time,.recent-kind { color:var(--color-text-secondary); font-size:11px; } }
.metadata { font-size:13px; color:var(--color-text-secondary); }.quiet { background:none; border:0; cursor:pointer; color:var(--color-text-secondary); }
.overview-more { position:relative; z-index:2; summary { cursor:pointer; list-style:none; padding:0 8px; color:var(--color-text-secondary); } > div { position:absolute; right:0; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:7px; padding:7px; min-width:160px; z-index:3; box-shadow:0 12px 30px #0002; } button { display:block; width:100%; background:none; border:0; text-align:left; padding:8px; color:var(--color-text); cursor:pointer; } }
.business-display { margin:20px 0; iframe { width:100%; min-height:600px; border:1px solid var(--gray-150); } }
.more-row { padding:16px 0; border-bottom:1px solid var(--gray-150); }
@media(max-width:1100px) { .overview-columns { grid-template-columns:minmax(0,1fr); } }
@media(max-width:760px) { .overview-workspace { padding-top:18px; } .overview-panel { padding:18px; }.attention-row { align-items:flex-start; } }
</style>
