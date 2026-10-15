<script setup>
import { inject, onBeforeUnmount, ref, watch } from 'vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { useUserStore } from '@/stores/user'
import { describeBoardError, runStatusEntries, runStatusLabel } from '@/utils/governanceBoard'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
const accessLost = inject('projectAccessLost', () => {})
const props = defineProps({ projectId: { type: String, required: true } })
const user = useUserStore(),
  board = ref({}),
  loading = ref(false),
  error = ref('')
const interventions = ref([]),
  historical = ref([])
let generation = 0
function failure(cause) {
  error.value = describeBoardError(cause)
  if ([401, 403, 404].includes(cause?.status || cause?.response?.status)) {
    board.value = {}
    interventions.value = []
    historical.value = []
    generation++
    loading.value = false
    accessLost()
  }
}
async function load() {
  const request = ++generation,
    id = props.projectId,
    owner = user.uid
  const current = () => request === generation && id === props.projectId && owner === user.uid
  loading.value = true
  error.value = ''
  try {
    const value = await api.getProjectBoard(id)
    const pages = {}
    for (const section of ['work', 'exceptions', 'historical_exceptions']) {
      const rows = []
      let offset = 0,
        total = 1
      while (offset < total) {
        const page = await api.getOverviewPage(id, section, offset, 100)
        if (!current()) return
        rows.push(...page.items)
        total = page.total
        offset += 100
      }
      pages[section] = rows
    }
    if (!current()) return
    board.value = value
    interventions.value = [
      ...pages.work.filter((item) => item.status === 'blocked' || item.overdue),
      ...pages.exceptions
    ]
    historical.value = pages.historical_exceptions
  } catch (cause) {
    if (current()) failure(cause)
  } finally {
    if (current()) loading.value = false
  }
}
watch(
  () => [props.projectId, user.uid],
  () => {
    board.value = {}
    interventions.value = []
    historical.value = []
    void load()
  },
  { immediate: true }
)
onBeforeUnmount(() => generation++)
</script>
<template>
  <section class="report-workspace" aria-label="督查与汇报">
    <div class="report-tools"><a-button :loading="loading" @click="load">刷新</a-button></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <p v-if="loading" role="status">正在读取督查事实…</p>
    <div class="report-columns"><div class="report-interventions"><section>
      <h2>需要介入</h2>
      <p v-if="!interventions.length">当前没有已记录的阻塞项。</p>
      <article v-for="(item, index) in interventions" :key="item.id || index">
        <RouterLink v-if="item.url" :to="item.url"
          ><strong>{{ item.title || item.task_title || item.message || item.reason }}</strong>
          <p>{{ item.summary || item.description || item.error_message }}</p></RouterLink
        >
        <p v-else>{{ item.title || item.task_title || item.message || item.reason }}</p>
      </article>
    </section>
    <details v-if="historical.length">
      <summary>历史执行异常 · {{ historical.length }}</summary>
      <article v-for="item in historical" :key="item.id">
        <RouterLink :to="item.url">{{ item.task_title || item.title || item.id }}</RouterLink>
        <p>{{ item.error_message }}</p>
      </article>
    </details>
    <details class="run-history">
      <summary>项目执行历史 · {{ (board.execution?.recent_runs || []).length }} 条近期记录</summary>
      <p>
        <a-tag
          v-for="entry in runStatusEntries(board.execution?.run_status_counts)"
          :key="entry.status"
          >{{ entry.label }} {{ entry.count }}</a-tag
        >
      </p>
      <h3>历史执行异常</h3>
      <p v-if="!board.execution?.blocked_runs?.length">暂无历史执行异常。</p>
      <article v-for="run in board.execution?.blocked_runs || []" :key="run.id">
        <strong>{{ run.agent_slug || run.id }} · {{ runStatusLabel(run.status) }}</strong>
        <p>{{ run.error_type }} {{ run.error_message }}</p>
        <time>{{ run.finished_at || run.created_at }}</time>
        <RouterLink
          v-if="run.conversation_thread_id"
          :to="{ name: 'AgentCompWithThreadId', params: { thread_id: run.conversation_thread_id } }"
          >在平台查看原执行会话</RouterLink
        >
      </article>
      <h3>近期执行</h3>
      <article v-for="run in board.execution?.recent_runs || []" :key="run.id">
        <strong>{{ run.agent_slug || run.id }} · {{ runStatusLabel(run.status) }}</strong>
        <p>{{ run.error_message }}</p>
        <time>{{ run.finished_at || run.created_at }}</time>
        <RouterLink
          v-if="run.conversation_thread_id"
          :to="{ name: 'AgentCompWithThreadId', params: { thread_id: run.conversation_thread_id } }"
          >在平台查看原执行会话</RouterLink
        >
      </article>
    </details>
    </div><section class="report-recent">
      <h2>近期汇报</h2>
      <RouterLink :to="{ name: 'AgentManageComp', query: { tab: 'schedules' } }"
        >在平台管理周期汇报计划</RouterLink
      >
      <p v-if="!board.governance?.reports?.length">暂无汇报。汇报产生于原执行与周期汇报链路。</p>
      <details v-for="item in board.governance?.reports || []" :key="item.id">
        <summary>
          {{ item.title || item.summary || item.report_type }} <time>{{ item.created_at }}</time>
        </summary>
        <MarkdownPreview :content="item.summary || ''" /><MarkdownPreview
          v-if="typeof item.content === 'string'"
          :content="item.content"
        />
        <dl v-else>
          <template v-for="(value, key) in item.content || {}" :key="key"
            ><dt>{{ key }}</dt>
            <dd>
              <MarkdownPreview v-if="typeof value === 'string'" :content="value" />
              <pre v-else>{{ JSON.stringify(value, null, 2) }}</pre>
            </dd></template
          >
        </dl>
        <p v-if="item.artifact_path">产物路径：{{ item.artifact_path }}</p>
        <details v-if="item.source_run_id">
          <summary>来源执行</summary>
          <code>{{ item.source_run_id }}</code>
        </details>
      </details>
    </section></div>
  </section>
</template>
<style scoped lang="less">
.report-workspace {
  max-width: 1100px;
  margin: auto;
  .report-tools {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 20px;
  }
  section {
    background: var(--gray-0);
    border: 1px solid var(--gray-150);
    border-radius: 10px;
    padding: 24px;
    margin-bottom: 24px;
  }
  h2 {
    font-size: 19px;
  }
  article,
  details {
    padding: 16px 0;
    border-bottom: 1px solid var(--gray-150);
  }
  summary {
    cursor: pointer;
  }
  time,
  p {
    color: var(--color-text-secondary);
  }
  a {
    color: var(--color-text);
    text-decoration: none;
  }
  a:hover strong {
    color: var(--main-color);
  }
  pre {
    white-space: pre-wrap;
    overflow-wrap: anywhere;
  }
}

.report-workspace { max-width:none; .report-tools { min-height:72px; padding:20px 0; margin-bottom:4px; } }.report-columns { display:grid; grid-template-columns:minmax(0,1.75fr) minmax(245px,1fr); gap:24px; align-items:start; }.report-interventions { min-width:0; >details { font-size:13px; } }.report-recent { min-width:0; }.report-columns section h2 { margin:0 0 18px; font-size:19px; }
@media(max-width:1100px) { .report-columns { grid-template-columns:minmax(0,1fr); } }
</style>
