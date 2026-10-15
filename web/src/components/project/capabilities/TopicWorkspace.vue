<script setup>
import { confirmationConditionsChanged } from '@/utils/topicFollowup'
import { themeReturnTarget } from '@/utils/projectThemeReturn'
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowLeft, Pencil, MoreHorizontal } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import TopicHistoryPanel from '@/components/project/TopicHistoryPanel.vue'
import DecisionHistoryPanel from '@/components/project/DecisionHistoryPanel.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { projectWorkApi } from '@/apis/project_work_api'
import { useUserStore } from '@/stores/user'
import {
  describeBoardError,
  governanceStatusLabel,
  topicAdmissionLabel,
  topicProgressLabel
} from '@/utils/governanceBoard'
import {
  clearGovernanceDrafts,
  getGovernanceDraft,
  setGovernanceDraft
} from '@/utils/governanceDrafts'

const props = defineProps({ projectId: { type: String, required: true } })
const accessLost = inject('projectAccessLost', () => {})
const user = useUserStore(),
  route = useRoute(),
  router = useRouter()
const topics = ref([]),
  decisions = ref([]),
  works = ref([]),
  selectedId = ref('')
const search = ref(''),
  showArchived = ref(false),
  admission = ref('all'),
  loading = ref(false),
  busy = ref(false),
  error = ref('')
const themeOrigin = computed(() =>
  themeReturnTarget(route.query.theme_return, user.uid, props.projectId)
)
const composer = ref(null),
  form = ref({}),
  formError = ref(''),
  discussionDrafts = ref({})
let generation = 0
const selected = computed(() => topics.value.find((item) => item.id === selectedId.value))
const achievements = ref({})
const decisionScope = ref('all')
const unlinkedDecisionCount = computed(() => decisions.value.filter(item => !item.topic_id).length)
const indexedDecisions = computed(() => decisionScope.value === 'unlinked' ? decisions.value.filter(item => !item.topic_id) : decisions.value)
const progress = ref('all'), historyPanel = ref(null), decisionExpanded = ref(new Set())
const detailVisible = computed(() => Boolean(route.query.topic_id || decisions.value.find(item => item.id === route.query.decision_id)?.topic_id || route.query.comment_id || route.query.revision))
function returnToDirectory() {
  const query = { ...route.query }
  for (const key of ['topic_id', 'decision_id', 'comment_id', 'revision', 'decision_revision']) delete query[key]
  return router.push({ query, hash: '' })
}
function toggleDecision(id, event) {
  const values = new Set(decisionExpanded.value)
  if (event.target.open) values.add(id)
  else values.delete(id)
  decisionExpanded.value = values
}
const topicSummary = (topic) => `${decisions.value.filter(item => item.topic_id === topic.id).length} 个决定 · ${works.value.filter(item => item.topic_id === topic.id).length} 项正式工作`
const updatedLabel = (raw) => raw ? new Date(raw).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : ''
const conflictingSource = computed(() => {
  const decision = decisions.value.find(item => item.id === route.query.decision_id)
  return Boolean(decision && route.query.topic_id && decision.topic_id !== route.query.topic_id)
})
const relatedDecisions = computed(() =>
  decisions.value.filter((item) => item.topic_id === selectedId.value)
)
const filtered = computed(() =>
  topics.value.filter(
    (item) =>
      (showArchived.value || !item.archived_at) &&
      (admission.value === 'all' || item.admission_status === admission.value) &&
      (progress.value === 'all' || (progress.value === 'achieved' ? achievements.value[item.id] : item.progress === progress.value)) &&
      `${item.title}\n${item.summary || ''}`
        .toLocaleLowerCase()
        .includes(search.value.toLocaleLowerCase())
  )
)
const capture = () => ({ project: props.projectId, user: user.uid, generation })
const current = (value) =>
  value.project === props.projectId && value.user === user.uid && value.generation === generation
const draftKey = (value) =>
  value.kind === 'edit'
    ? `theme-topic-edit:${value.id}`
    : value.kind === 'decision'
      ? `theme-decision-create:${value.id || 'independent'}:${value.relation}:${value.target || ''}`
      : 'theme-topic-create'
function failure(cause) {
  error.value = describeBoardError(cause)
  if ([401, 403].includes(cause?.status || cause?.response?.status)) {
    generation++
    loading.value = false
    busy.value = false
    clearGovernanceDrafts(user.uid, props.projectId)
    selectedId.value = ''
    achievements.value = {}
    discussionDrafts.value = {}
    topics.value = []
    decisions.value = []
    works.value = []
    composer.value = null
    form.value = {}
    accessLost()
  }
}

/** 原列表拥有准入和历史，指定深链缺失时不选择相邻对象。 */
async function load() {
  const captured = capture()
  loading.value = true
  error.value = ''
  try {
    const [topicRows, decisionRows, workRows] = await Promise.all([
      api.listTopics(captured.project, true),
      api.listDecisions(captured.project),
      projectWorkApi.listTasks(captured.project)
    ])
    if (!current(captured)) return
    topics.value = topicRows
    decisions.value = decisionRows
    works.value = workRows
    if (progress.value === 'achieved') await setProgress('achieved')
    if (!current(captured)) return
    const decision = decisionRows.find((item) => item.id === route.query.decision_id)
    const requested = String(route.query.topic_id || decision?.topic_id || '')
    if (requested) selectedId.value = requested
    else if (!topics.value.some((item) => item.id === selectedId.value))
      selectedId.value = topics.value.find((item) => !item.archived_at)?.id || ''
  } catch (cause) {
    if (current(captured)) failure(cause)
  } finally {
    if (current(captured)) loading.value = false
  }
}
/** 达成筛选读取原确认历史，不把决定或任务完成当成目标达成。 */
async function setProgress(value) {
  progress.value = value
  if (value !== 'achieved') return
  const captured = capture()
  loading.value = true
  try {
    const rows = await Promise.all(topics.value.map(async topic => {
      const result = await api.getTopicFollowup(captured.project, topic.id)
      const latest = result.confirmations[0]
      return [topic.id, Boolean(latest && latest.action !== 'withdraw' && !confirmationConditionsChanged(topic, latest))]
    }))
    if (current(captured)) achievements.value = Object.fromEntries(rows)
  } catch (cause) { if (current(captured)) failure(cause) }
  finally { if (current(captured)) loading.value = false }
}
function choose(id) {
  selectedId.value = id
  const query = { ...route.query }
  for (const key of ['decision_id', 'decision_revision', 'revision', 'comment_id']) delete query[key]
  return router.push({ query: { ...query, topic_id: id } })
}

/** 表单草稿冻结原修订，冲突后不改换依据自动重试。 */
function open(kind, target = null, relation = 'ordinary') {
  const captured = capture()
  composer.value = {
    kind,
    id: target ? target.topic_id : selected.value?.id,
    relation,
    target: target?.id || null,
    scope: captured
  }
  const saved = getGovernanceDraft(captured.user, captured.project, draftKey(composer.value))
  form.value =
    saved ||
    (kind === 'edit'
      ? {
          title: selected.value.title,
          summary: selected.value.summary || '',
          expected_outcome: selected.value.expected_outcome || '',
          verification_conditions: selected.value.verification_conditions || '',
          reason: '',
          expected_revision: selected.value.revision_number
        }
      : kind === 'decision'
        ? {
            title: '',
            conclusion: '',
            rationale: '',
            topic_id: composer.value.id || null,
            relation_type: relation,
            target_decision_id: target?.id || null
          }
        : { title: '', summary: '' })
  formError.value = ''
}
watch(
  form,
  () => {
    if (composer.value && current(composer.value.scope))
      setGovernanceDraft(user.uid, props.projectId, draftKey(composer.value), form.value)
  },
  { deep: true }
)
watch(
  discussionDrafts,
  () => {
    for (const [id, draft] of Object.entries(discussionDrafts.value))
      setGovernanceDraft(user.uid, props.projectId, `theme-discussion:${id}`, draft)
  },
  { deep: true, flush: 'sync' }
)
function discussionDraft(id) {
  if (!discussionDrafts.value[id])
    discussionDrafts.value[id] = getGovernanceDraft(
      user.uid,
      props.projectId,
      `theme-discussion:${id}`
    ) || { content: '', discussionType: 'discussion' }
  return discussionDrafts.value[id]
}

/** 写操作使用准确对象、原API与原修订，成功后回读业务Owner。 */
async function submit() {
  const target = composer.value
  if (!target || busy.value || !current(target.scope)) return
  if (!form.value.title?.trim()) {
    formError.value = '请填写标题'
    return
  }
  if (target.kind === 'edit' && !form.value.reason?.trim()) {
    formError.value = '请填写修改原因'
    return
  }
  if (
    target.kind === 'decision' &&
    (!form.value.conclusion?.trim() ||
      (form.value.relation_type !== 'ordinary' && !form.value.target_decision_id))
  ) {
    formError.value = '请填写结论及补充或替代的目标准确决定'
    return
  }
  busy.value = true
  formError.value = ''
  try {
    const payload = { ...form.value }
    const result =
      target.kind === 'edit'
        ? await api.updateTopic(target.scope.project, target.id, payload)
        : target.kind === 'decision'
          ? await api.createDecision(target.scope.project, payload)
          : await api.createTopic(target.scope.project, payload)
    if (!current(target.scope)) return
    setGovernanceDraft(user.uid, props.projectId, draftKey(target), null)
    composer.value = null
    if (target.kind === 'create') await choose(result.id)
    await load()
  } catch (cause) {
    if (current(target.scope)) {
      formError.value = describeBoardError(cause)
      if ([401, 403].includes(cause?.status)) failure(cause)
    }
  } finally {
    if (current(target.scope)) busy.value = false
  }
}
async function review(approve) {
  if (busy.value || !selected.value) return
  const captured = capture(),
    id = selected.value.id
  busy.value = true
  try {
    await api.reviewTopic(captured.project, id, approve)
    if (current(captured)) await load()
  } catch (cause) {
    if (current(captured)) failure(cause)
  } finally {
    if (current(captured)) busy.value = false
  }
}
function selectDecision(id) {
  return router.push({ query: { ...route.query, decision_id: id, topic_id: undefined, comment_id: undefined, revision: undefined } })
}
watch(
  () => [route.query.topic_id, route.query.decision_id],
  ([id, decisionId]) => {
    const decision = decisions.value.find((item) => item.id === decisionId)
    if (id || decision?.topic_id) selectedId.value = String(id || decision.topic_id)
    if (decisionId) decisionExpanded.value = new Set([...decisionExpanded.value, decisionId])
  }
)
watch(
  () => [props.projectId, user.uid],
  () => {
    generation++
    topics.value = []
    achievements.value = {}
    decisions.value = []
    works.value = []
    selectedId.value = ''
    composer.value = null
    discussionDrafts.value = {}
    busy.value = false
    void load()
  },
  { immediate: true }
)
/** 准确决定就绪后展开并定位，不跳到相邻记录。 */
watch(() => [route.query.decision_id, relatedDecisions.value.map(item => item.id).join(','), loading.value], async ([id, , pending]) => {
  if (!id || pending || !relatedDecisions.value.some(item => item.id === id)) return
  decisionExpanded.value = new Set([...decisionExpanded.value, id])
  await nextTick()
  const element = typeof document === 'undefined' ? null : document.getElementById(`topic-decision-${id}`)
  element?.scrollIntoView({ block: 'center' })
  element?.focus({ preventScroll: true })
})
onBeforeUnmount(() => generation++)
</script>

<template>
  <section class="topic-workspace" aria-label="议题工作区">
    <RouterLink v-if="themeOrigin" :to="themeOrigin" class="source-return">返回来源</RouterLink>
    <div v-if="!detailVisible" class="collection-tools">
      <div class="collection-filters"><a-input v-model:value="search" aria-label="搜索议题" placeholder="搜索标题或关键词" allow-clear />
        <a-select :value="progress" aria-label="筛选议题" @change="setProgress"><a-select-option value="all">全部进展</a-select-option><a-select-option value="open">研讨中</a-select-option><a-select-option value="decided">已形成决定</a-select-option><a-select-option value="achieved">目标已达成</a-select-option><a-select-option value="closed">已关闭</a-select-option></a-select>
        <details class="directory-more"><summary aria-label="更多议题筛选"><MoreHorizontal :size="18" /></summary><div><a-select v-model:value="admission" aria-label="议题准入筛选"><a-select-option value="all">全部准入</a-select-option><a-select-option value="proposed">待纳入</a-select-option><a-select-option value="canonical">已纳入</a-select-option><a-select-option value="rejected">已拒绝</a-select-option></a-select><a-checkbox v-model:checked="showArchived">归档</a-checkbox></div></details>
      </div><a-button type="primary" @click="open('create')">新建</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="error"><template #action><a-button @click="load">重试</a-button></template></a-alert>
    <p v-if="loading" role="status">正在读取议题…</p>
    <a-alert v-if="conflictingSource" type="warning" show-icon message="入口议题与决定真实来源不一致，原地址保留。"><template #action><a-button @click="selectDecision(route.query.decision_id)">打开决定真实来源</a-button></template></a-alert>
    <section v-if="!detailVisible" class="topic-directory" aria-label="议题目录">
      <RouterLink v-for="topic in filtered" :key="topic.id" class="topic-directory-row object-target" :to="{ query: { theme_page: route.query.theme_page, topic_id: topic.id } }"><div><strong>{{ topic.title }}</strong><p>{{ topicSummary(topic) }}</p></div><span class="topic-status">{{ topic.archived_at ? '已归档' : topicProgressLabel(topic.progress) }}</span></RouterLink>
      <p v-if="!filtered.length && !loading" class="metadata">没有符合条件的议题。</p>
    </section>
    <div v-else class="topic-detail-layout">
      <div class="object-toolbar"><button type="button" class="quiet return-directory" @click="returnToDirectory"><ArrowLeft :size="16" />返回目录</button><div class="toolbar-actions" v-if="selected"><button v-if="!selected.archived_at" class="icon-control" type="button" aria-label="编辑正文" :disabled="busy" @click="open('edit')"><Pencil :size="18" /></button><button class="icon-control" type="button" aria-label="生命周期与更多" @click="historyPanel?.openMaintenance()"><MoreHorizontal :size="18" /></button></div></div>
      <article v-if="selected" class="topic-reading-body">
        <div class="topic-document-surface"><h1>{{ selected.title }}</h1><div class="object-meta"><span class="topic-status">{{ topicProgressLabel(selected.progress) }}</span><span v-if="selected.admission_status !== 'canonical'">{{ topicAdmissionLabel(selected.admission_status) }}</span><span>正文 v{{ selected.revision_number }}</span><span v-if="selected.updated_at">更新于 {{ updatedLabel(selected.updated_at) }}</span><span v-if="selected.archived_at">已归档</span></div>
        <div class="topic-prose"><MarkdownPreview :content="selected.summary || '尚未填写正文。'" /><template v-if="selected.expected_outcome"><h2>预期结果</h2><MarkdownPreview :content="selected.expected_outcome" /></template><template v-if="selected.verification_conditions"><h2>验证条件</h2><MarkdownPreview :content="selected.verification_conditions" /></template></div>
        <div v-if="selected.admission_status === 'proposed' && !selected.archived_at" class="admission-actions"><span>纳入审核</span><a-button :disabled="busy" danger @click="review(false)">拒绝纳入</a-button><a-button :disabled="busy" @click="review(true)">纳入议题</a-button></div>
        </div>
        <details class="topic-decisions" :open="Boolean(route.query.decision_id && relatedDecisions.some(item => item.id === route.query.decision_id))"><summary>决策 <span class="count-badge">{{ relatedDecisions.length }}</span></summary><div class="decision-rows">
          <details v-for="decision in relatedDecisions" :key="decision.id" :id="`topic-decision-${decision.id}`" tabindex="-1" class="decision-row" :open="decisionExpanded.has(decision.id) || route.query.decision_id === decision.id" @toggle="toggleDecision(decision.id, $event)"><summary><span>{{ decision.title }}</span><span class="topic-status">{{ governanceStatusLabel(decision.status) }}</span></summary><div class="decision-content"><DecisionHistoryPanel v-if="decisionExpanded.has(decision.id) || route.query.decision_id === decision.id" v-show="!loading" embedded :project-id="projectId" :decisions="[decision]" :topics="topics" :selected-id="decision.id" @updated="load" @visibility-lost="failure" @select="selectDecision" @compose="(decision, relation) => open('decision', decision, relation)" @topic="choose" /></div></details>
          <button v-if="!selected.archived_at" class="quiet new-decision" @click="open('decision')">新建决策</button><p v-if="!relatedDecisions.length" class="metadata">尚无决定；研讨和工作可独立开展。</p>
        </div></details>
        <TopicHistoryPanel ref="historyPanel" :key="`${projectId}:${selected.id}`" :project-id="projectId" :topic="selected" :decisions="decisions" :works="works.filter((item) => item.topic_id === selected.id)" :draft="discussionDraft(selected.id)" presentation="continuous" @updated="load" @visibility-lost="failure" />
      </article>
      <p v-else-if="!loading" role="status">指定议题不存在或无权访问，原地址保留。</p>
    </div>
    <details
      v-if="!detailVisible"
      class="independent-decisions"
      :open="
        Boolean(
          route.query.decision_id &&
          !decisions.find((item) => item.id === route.query.decision_id)?.topic_id
        )
      "
    >
      <summary><span class="decision-index-title">决定索引</span><span class="decision-index-count">{{ decisions.length }} 条决定 · {{ unlinkedDecisionCount }} 条未关联议题</span><span class="decision-index-chevron" aria-hidden="true">⌄</span></summary>
      <div class="decision-index-tools"><div class="decision-scope" role="group" aria-label="决定查看范围"><button type="button" :aria-pressed="decisionScope === 'all'" @click="decisionScope = 'all'">全部决定<span>{{ decisions.length }}</span></button><button type="button" :aria-pressed="decisionScope === 'unlinked'" @click="decisionScope = 'unlinked'">未关联议题<span>{{ unlinkedDecisionCount }}</span></button></div><a-tooltip title="创建暂不关联议题的决定草案，仍需按原流程批准。"><a-button size="small" @click="open('decision', { id: null, topic_id: null })">新建独立决定</a-button></a-tooltip></div>
      <a-alert
        v-if="
          route.query.decision_id &&
          !loading &&
          !decisions.some((item) => item.id === route.query.decision_id)
        "
        type="warning"
        message="指定决定不存在或无权访问，原地址保留。"
      />
      <DecisionHistoryPanel
        v-show="!loading"
        :project-id="projectId"
        :decisions="indexedDecisions"
        show-source
        :topics="topics"
        :selected-id="String(route.query.decision_id || '')"
        @updated="load"
        @visibility-lost="failure"
        @select="selectDecision"
        @compose="(decision, relation) => open('decision', decision, relation)"
        @topic="choose"
      />
    </details>
    <a-modal
      :open="!!composer"
      :title="
        { create: '新建议题', edit: '修改议题提议', decision: '新建决定草案' }[composer?.kind]
      "
      :width="820"
      :mask-closable="false"
      :confirm-loading="busy"
      :closable="!busy"
      :keyboard="!busy"
      :cancel-button-props="{ disabled: busy }"
      ok-text="保存"
      cancel-text="保留草稿并关闭"
      @ok="submit"
      @cancel="composer = null"
    >
      <a-alert v-if="formError" type="error" show-icon :message="formError" />
      <a-form layout="vertical"
        ><a-form-item label="标题" required
          ><a-input v-model:value="form.title" aria-label="议题或决定标题" :disabled="busy"
        /></a-form-item>
        <template v-if="composer?.kind === 'decision'"
          ><a-form-item label="关联议题"
            ><a-select v-model:value="form.topic_id" allow-clear aria-label="关联议题"
              ><a-select-option
                v-for="topic in topics.filter((item) => !item.archived_at)"
                :key="topic.id"
                :value="topic.id"
                >{{ topic.title }}</a-select-option
              ></a-select
            ></a-form-item
          ><a-form-item label="形成方式"
            ><a-select
              v-model:value="form.relation_type"
              aria-label="决定形成方式"
              @change="form.target_decision_id = null"
              ><a-select-option value="ordinary">普通决定</a-select-option
              ><a-select-option value="supplement">补充决定</a-select-option
              ><a-select-option value="replacement">整条替代</a-select-option></a-select
            ></a-form-item
          ><a-form-item v-if="form.relation_type !== 'ordinary'" label="目标有效决定" required
            ><a-select v-model:value="form.target_decision_id" aria-label="目标有效决定"
              ><a-select-option
                v-for="decision in decisions.filter((item) => item.status === 'approved')"
                :key="decision.id"
                :value="decision.id"
                >{{ decision.title }}</a-select-option
              ></a-select
            ></a-form-item
          ><a-form-item label="结论" required
            ><a-textarea
              v-model:value="form.conclusion"
              aria-label="决定结论"
              :disabled="busy"
              :auto-size="{ minRows: 6, maxRows: 18 }" /></a-form-item
          ><a-form-item label="理由与依据"
            ><a-textarea
              v-model:value="form.rationale"
              aria-label="决定理由"
              :disabled="busy"
              :auto-size="{ minRows: 4, maxRows: 12 }" /></a-form-item
        ></template>
        <template v-else
          ><a-form-item label="正文"
            ><a-textarea
              v-model:value="form.summary"
              aria-label="议题正文"
              :disabled="busy"
              :maxlength="100000"
              :auto-size="{ minRows: 12, maxRows: 24 }" /></a-form-item
          ><template v-if="composer?.kind === 'edit'"
            ><a-form-item label="预期结果"
              ><a-textarea
                v-model:value="form.expected_outcome"
                aria-label="预期结果"
                :disabled="busy" /></a-form-item
            ><a-form-item label="核对条件"
              ><a-textarea
                v-model:value="form.verification_conditions"
                aria-label="核对条件"
                :disabled="busy" /></a-form-item
            ><a-form-item label="修改原因" required
              ><a-input v-model:value="form.reason" aria-label="议题修改原因" :disabled="busy"
            /></a-form-item>
            <p class="metadata">
              基于修订 {{ form.expected_revision }}，冲突后保留草稿供核对。
            </p></template
          ></template
        >
      </a-form>
    </a-modal>
  </section>
</template>

<style scoped lang="less">
.topic-workspace { color:var(--color-text); }
.collection-tools,.collection-filters { display:flex; align-items:center; gap:12px; min-width:0; }
.collection-tools { justify-content:space-between; padding:20px 0; margin-bottom:4px; min-height:72px; > .ant-btn { flex-shrink:0; } }
.collection-filters { flex:1; > :deep(.ant-input-affix-wrapper) { width:260px; min-width:80px; } > :deep(.ant-select) { min-width:140px; } }
.topic-directory { padding:4px 24px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; }
.topic-directory-row { display:flex; align-items:center; gap:14px; padding:16px 0; border-bottom:1px solid var(--gray-150); text-decoration:none; color:var(--color-text); &:last-child { border:0; } > div { flex:1; min-width:0; } strong { font-size:16px; font-weight:600; } p { margin:5px 0 0; font-size:13px; color:var(--color-text-secondary); } &:hover strong { color:var(--main-color); } }
.topic-status { display:inline-block; padding:3px 8px; border-radius:5px; font-size:11px; background:var(--main-10); color:var(--main-color); }
.topic-detail-layout { max-width:960px; margin:0 auto; padding-bottom:24px; }
.object-toolbar { display:flex; justify-content:space-between; align-items:center; padding:18px 0 14px; }.toolbar-actions { display:flex; gap:8px; }.quiet,.icon-control { border:0; background:none; color:var(--color-text-secondary); min-height:38px; cursor:pointer; border-radius:6px; }.return-directory { display:flex; align-items:center; gap:6px; padding:0; }.icon-control { display:grid; place-items:center; min-width:38px; padding:7px; &:hover { background:var(--gray-100); } }
.topic-reading-body { padding:6px 4px 0; min-width:0; h1 { font-size:26px; line-height:1.6; letter-spacing:0; margin:0; } }
.object-meta { display:flex; align-items:center; gap:15px; margin:12px 0 28px; color:var(--color-text-secondary); font-size:12px; flex-wrap:wrap; }
.topic-prose { font-size:16px; line-height:1.9; :deep(.yk-markdown-preview) { font-size:16px; line-height:1.9; } :deep(h2) { font-size:17px; margin-top:22px; } }
.topic-decisions { margin:32px 0 26px; > summary { cursor:pointer; font-weight:600; font-size:16px; padding:12px 0; } }
.count-badge { margin-left:8px; font-size:11px; color:var(--color-text-secondary); border:1px solid var(--gray-150); border-radius:4px; padding:2px 6px; }
.decision-rows { margin-top:8px; border:1px solid var(--gray-150); border-radius:8px; background:var(--gray-0); padding:4px 16px; }
.decision-row { border-bottom:1px solid var(--gray-150); > summary { cursor:pointer; list-style:none; display:flex; align-items:center; justify-content:space-between; gap:16px; padding:15px 0; font-size:14px; &:before { content:'›'; color:var(--color-text-secondary); } > span:first-child { flex:1; } } &[open] > summary:before { transform:rotate(90deg); } }
.decision-content { padding:0 20px 20px; font-size:14px; }.new-decision { margin:8px 0; }
.metadata { color:var(--color-text-secondary); font-size:13px; }.admission-actions { display:flex; align-items:center; gap:8px; flex-wrap:wrap; > span { margin-right:auto; } }
.independent-decisions { margin-top:24px; border:1px solid var(--gray-150); border-radius:10px; background:var(--gray-0); padding:0 20px 16px; >summary { display:flex; align-items:center; gap:12px; cursor:pointer; list-style:none; padding:18px 0; } >summary::-webkit-details-marker { display:none; } &:not([open]) { padding-bottom:0; } }
.decision-index-title { font-size:15px; font-weight:600; color:var(--color-text); }.decision-index-count { font-size:12px; color:var(--color-text-secondary); }.decision-index-chevron { margin-left:auto; color:var(--color-text-secondary); transform:rotate(-90deg); }.independent-decisions[open] .decision-index-chevron { transform:none; }
.decision-index-tools { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; margin-bottom:16px; }.decision-scope { display:flex; gap:4px; border-radius:7px; padding:3px; background:var(--gray-50); >button { display:flex; align-items:center; gap:8px; border:0; border-radius:5px; padding:7px 10px; font-size:13px; color:var(--color-text-secondary); background:transparent; cursor:pointer; } >button[aria-pressed=true] { background:var(--gray-0); color:var(--main-color); box-shadow:0 1px 3px #0000000a; } >button span { font-size:11px; color:var(--color-text-secondary); } }
@media(max-width:600px){.independent-decisions>summary { flex-wrap:wrap; gap:6px; }.decision-index-count { flex-basis:calc(100% - 30px); order:3; }.decision-index-tools { align-items:flex-start; }}
.directory-more { position:relative; summary { list-style:none; cursor:pointer; display:grid; place-items:center; min-height:38px; } > div { display:flex; gap:12px; align-items:center; position:absolute; left:0; top:100%; min-width:240px; padding:16px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:7px; z-index:3; :deep(.ant-select) { width:120px; } } }
button:focus-visible, a:focus-visible, summary:focus-visible { outline:2px solid var(--main-color); outline-offset:3px; }
@media(max-width:760px) { .collection-filters { gap:6px; flex-wrap:wrap; > :deep(.ant-input-affix-wrapper) { width:150px; } > :deep(.ant-select) { min-width:110px; } } .topic-directory { padding:4px 18px; }.topic-directory-row { align-items:flex-start; }.topic-reading-body h1 { font-size:23px; }.object-meta { gap:9px; }.decision-content { padding:0 4px 16px; } }

.topic-reading-body { padding:0; }
.topic-document-surface { background:var(--gray-0); border:1px solid var(--gray-150); border-radius:12px; padding:30px 32px; }
.topic-document-surface .object-meta { padding-bottom:18px; margin-bottom:24px; border-bottom:1px solid var(--gray-150); }
.topic-prose { color:var(--color-text); :deep(h2) { margin:28px 0 12px; font-weight:600; } }
.topic-decisions { margin:20px 0 28px; border:1px solid var(--gray-150); border-radius:10px; background:var(--gray-0); >summary { padding:16px 20px; font-size:15px; } .decision-rows { margin:0; border:0; border-top:1px solid var(--gray-150); border-radius:0 0 10px 10px; padding:4px 20px 12px; } }
.admission-actions { margin-top:24px; padding-top:18px; border-top:1px solid var(--gray-150); }
@media(max-width:760px) { .topic-document-surface { padding:22px 18px; }.topic-decisions>summary { padding:14px 18px; } }
</style>
