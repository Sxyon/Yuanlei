<template>
  <section>
    <div class="toolbar">
      <span>{{ kind === 'history' ? 'Git 审批与执行历史' : '工作空间占用与排队' }}</span>
      <a-button size="small" :loading="loading" @click="load()">刷新</a-button>
    </div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-spin :spinning="loading">
      <a-empty
        v-if="!rows.length && !error && !loading"
        :description="kind === 'history' ? '暂无 Git 审批记录' : '当前没有工作空间占用或等待任务'"
      />
      <template v-if="kind === 'occupancies'">
        <article v-for="resource in groups" :key="resource.id" class="activity-card">
          <h4>{{ resource.name }}</h4>
          <div v-for="slot in resource.rows" :key="slot.id" class="occupancy">
            <a-tag :color="slot.status === 'queued' ? 'orange' : 'blue'">{{
              slot.status === 'queued'
                ? slot.queue_position
                  ? `等待第 ${slot.queue_position} 位`
                  : '等待同任务执行结束'
                : '当前占用'
            }}</a-tag>
            <strong>{{ slot.scope_label }}</strong>
            <p>
              {{ slot.usage_mode === 'worktree' ? '隔离工作树' : '共享项目目录' }} ·
              {{ slot.workspace_path }} · {{ slot.branch }}
            </p>
            <p>
              {{
                slot.status === 'queued'
                  ? '等待工作空间分配'
                  : slot.lease_expired
                    ? '执行 lease 已过期，等待恢复处理'
                    : slot.active_execution
                      ? `正在执行 · ${slot.active_agent}`
                      : '执行已停止，任务仍保留工作空间'
              }}
              · {{ time(slot.requested_at) }}
            </p>
            <p v-if="slot.heartbeat_at">
              最近心跳：{{ time(slot.heartbeat_at) }} · lease 截止：{{
                time(slot.lease_expires_at)
              }}
            </p>
            <a-popconfirm
              title="确认释放？活动执行树或未提交内容将阻止释放。"
              @confirm="release(slot)"
            >
              <a-button size="small" :disabled="slot.active_execution || !!busy">释放占用</a-button>
            </a-popconfirm>
          </div>
        </article>
      </template>
      <template v-else>
        <article v-for="row in rows" :key="row.id" class="activity-card">
          <div class="toolbar">
            <strong>{{ actionLabel(row.action) }} · {{ repositoryName(row.repository_id) }}</strong>
            <a-tag :color="statusColor(row.status)">{{ statusLabel(row.status) }}</a-tag>
          </div>
          <p>
            {{ row.branch }}<template v-if="row.target_branch"> → {{ row.target_branch }}</template>
          </p>
          <p>
            {{ row.agent_slug ? `申请智能体：${row.agent_slug}` : '人工操作' }} ·
            {{ time(row.created_at) }}
          </p>
          <p>
            {{
              row.approval_kind === 'automatic'
                ? '自动批准'
                : row.approval_kind === 'human'
                  ? '人工决定'
                  : '等待人工决定'
            }}
            · {{ row.approval_reason }}
          </p>
          <a-button size="small" @click="selected = row">查看动作与时间线</a-button>
        </article>
        <div class="toolbar">
          <a-button :disabled="offset === 0 || loading" @click="changePage(-1)">上一页</a-button>
          <span>第 {{ offset / pageSize + 1 }} 页</span>
          <a-button :disabled="rows.length < pageSize || loading" @click="changePage(1)"
            >下一页</a-button
          >
        </div>
      </template>
    </a-spin>
    <a-modal
      :open="!!selected"
      title="Git 动作记录"
      width="900px"
      :footer="null"
      @cancel="selected = null"
    >
      <template v-if="selected">
        <a-alert v-if="error" type="error" show-icon :message="error" />
        <p>
          {{ actionLabel(selected.action) }} · {{ selected.branch
          }}<template v-if="selected.target_branch"> → {{ selected.target_branch }}</template>
        </p>
        <a-timeline>
          <a-timeline-item
            >申请 · {{ time(selected.created_at) }} ·
            {{ selected.agent_slug || '项目所有者' }}</a-timeline-item
          >
          <a-timeline-item v-if="selected.approved_at"
            >{{ selected.status === 'rejected' ? '拒绝' : '批准' }} ·
            {{ time(selected.approved_at) }} · {{ selected.approval_reason }}</a-timeline-item
          >
          <a-timeline-item v-if="selected.started_at"
            >开始执行 · {{ time(selected.started_at) }}</a-timeline-item
          >
          <a-timeline-item
            v-if="selected.finished_at"
            :color="selected.status === 'failed' ? 'red' : 'green'"
            >{{ statusLabel(selected.status) }} · {{ time(selected.finished_at) }}</a-timeline-item
          >
        </a-timeline>
        <p v-if="selected.message">提交说明：{{ selected.message }}</p>
        <a-alert v-if="selected.error" type="error" show-icon :message="selected.error" />
        <details>
          <summary>追溯信息与冻结快照</summary>
          <p>
            运行：{{ selected.run_id || '人工操作' }} · 任务作用域：{{
              selected.scope_key || '项目资源'
            }}
          </p>
          <p>
            批准者：{{ selected.approved_by || '尚未决定' }} · 执行任务：{{
              selected.task_id || '尚未创建'
            }}
          </p>
          <p>HEAD：{{ selected.expected_head }}</p>
          <p v-if="selected.expected_tree">内容树：{{ selected.expected_tree }}</p>
          <p v-if="selected.expected_base">目标 HEAD：{{ selected.expected_base }}</p>
        </details>
        <pre>{{ selected.diff || '此申请没有文件内容差异' }}</pre>
        <p v-if="selected.result?.committed_sha">实际提交：{{ selected.result.committed_sha }}</p>
        <p v-if="selected.result?.pushed_sha">远端确认：{{ selected.result.pushed_sha }}</p>
        <p v-if="selected.result?.merged">合并请求已由 Gitea 确认合并</p>
        <div v-if="selected.status === 'pending'" class="toolbar">
          <a-popconfirm
            title="批准记录中的固定快照并执行？执行前会再次检查，变化后将拒绝执行。"
            @confirm="decide(true)"
          >
            <a-button type="primary" :loading="busy === 'decision'">批准并执行</a-button>
          </a-popconfirm>
          <a-button danger :disabled="!!busy" @click="decide(false)">拒绝申请</a-button>
        </div>
      </template>
    </a-modal>
  </section>
</template>
<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { projectApi } from '@/apis/project_api'
const props = defineProps({
  projectId: { type: String, required: true },
  kind: { type: String, required: true },
  resources: { type: Array, default: () => [] }
})
const rows = ref([]),
  selected = ref(null),
  loading = ref(false),
  busy = ref(''),
  error = ref(''),
  offset = ref(0)
const pageSize = 50
let generation = 0,
  loadVersion = 0,
  timer
const repositoryName = (id) => props.resources.find((item) => item.id === id)?.alias || '项目仓库'
const groups = computed(() =>
  [...new Set(rows.value.map((row) => row.repository_id))].map((id) => ({
    id,
    name: repositoryName(id),
    rows: rows.value
      .filter((row) => row.repository_id === id)
      .sort((a, b) => {
        if (a.status !== b.status) return a.status === 'owned' ? -1 : 1
        return (
          (a.queue_position || 0) - (b.queue_position || 0) ||
          a.requested_at.localeCompare(b.requested_at)
        )
      })
  }))
)
const load = async (quiet = false) => {
  const version = generation,
    requestVersion = ++loadVersion
  if (!quiet) loading.value = true
  try {
    const result =
      props.kind === 'history'
        ? await projectApi.getGitActions(props.projectId, { offset: offset.value, limit: pageSize })
        : await projectApi.getGitOccupancies(props.projectId)
    if (version !== generation || requestVersion !== loadVersion) return
    rows.value = result
    if (selected.value)
      selected.value = result.find((row) => row.id === selected.value.id) || selected.value
    error.value = ''
  } catch (failure) {
    if (version === generation && requestVersion === loadVersion)
      error.value = failure?.message || '读取 Git 记录失败'
  } finally {
    if (version === generation && requestVersion === loadVersion) loading.value = false
  }
}
const changePage = (direction) => {
  generation++
  selected.value = null
  offset.value += direction * pageSize
  load()
}
const decide = async (approve) => {
  if (!selected.value || busy.value) return
  const version = generation
  busy.value = 'decision'
  try {
    const result = await projectApi.decideGitAction(props.projectId, selected.value.id, approve)
    if (version !== generation) return
    selected.value = result
    await load(true)
  } catch (failure) {
    if (version === generation) error.value = failure?.message || '审批失败'
  } finally {
    if (version === generation) busy.value = ''
  }
}
const release = async (slot) => {
  if (busy.value) return
  const version = generation
  busy.value = 'release'
  try {
    await projectApi.releaseGitResource(props.projectId, slot.repository_id, slot.scope_key)
    if (version === generation) await load(true)
  } catch (failure) {
    if (version === generation) error.value = failure?.message || '释放失败'
  } finally {
    if (version === generation) busy.value = ''
  }
}
watch(
  [() => props.projectId, () => props.kind],
  () => {
    generation++
    clearInterval(timer)
    rows.value = []
    selected.value = null
    offset.value = 0
    busy.value = ''
    error.value = ''
    load()
    timer = setInterval(() => load(true), 5000)
  },
  { immediate: true }
)
onBeforeUnmount(() => {
  generation++
  clearInterval(timer)
})
const actionLabel = (value) => ({ commit: '提交', push: '推送', merge: '合并' })[value] || value
const statusLabel = (value) =>
  ({
    pending: '待人工批准',
    approved: '已批准，等待执行',
    running: '正在执行',
    succeeded: '执行成功',
    failed: '执行失败，需核对',
    rejected: '已拒绝'
  })[value] || value
const statusColor = (value) =>
  value === 'succeeded'
    ? 'green'
    : value === 'failed'
      ? 'red'
      : value === 'pending'
        ? 'orange'
        : 'blue'
const time = (value) => (value ? new Date(value).toLocaleString() : '—')
</script>
<style scoped>
.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  margin: 12px 0;
  flex-wrap: wrap;
}
.activity-card {
  padding: 12px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  margin: 12px 0;
}
.occupancy {
  padding: 12px 0;
  border-top: 1px solid var(--gray-150);
}
p {
  overflow-wrap: anywhere;
}
pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 400px;
  overflow: auto;
  padding: 12px;
  background: var(--gray-50);
}
</style>
