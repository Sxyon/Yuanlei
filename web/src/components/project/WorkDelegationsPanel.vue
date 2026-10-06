<template>
  <section>
    <h2>编码与外部委派 <a-button size="small" @click="load">刷新记录</a-button></h2>
    <p>从本工作发起；当次来源固定保存，委派结果不自动改变工作状态。</p>
    <div class="delegation-controls">
      <a-select
        v-model:value="agentSlug"
        placeholder="选择项目数字员工"
        aria-label="编码委派数字员工"
        ><a-select-option v-for="agent in agents" :key="agent.slug" :value="agent.slug">{{
          agent.name || agent.slug
        }}</a-select-option></a-select
      >
      <a-select v-model:value="executor" aria-label="委派执行器"
        ><a-select-option v-for="key in enabled" :key="key" :value="key">{{ key }}</a-select-option
        ><a-select-option value="multica">Multica（需渠道配置）</a-select-option></a-select
      >
      <a-button
        :loading="busy"
        :disabled="ended || (executor !== 'multica' && (!agentSlug || !enabled.includes(executor)))"
        @click="dispatch"
        >委派执行</a-button
      >
    </div>
    <p v-if="agentSlug && !enabled.length">该数字员工未启用编码执行器，可在数字员工设置中配置。</p>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <p v-if="loading">读取委派记录…</p>
    <p v-else-if="!items.length">暂无本工作的外部委派记录。</p>
    <ul>
      <li v-for="item in items" :key="item.operation_id">
        {{ item.executor_key }} · {{ statusLabel(item.dispatch_state) }}
        <span v-if="item.remote_status && item.remote_status !== item.dispatch_state">
          · {{ statusLabel(item.remote_status) }}</span
        >
        ·
        {{ formatDateTime(item.created_at) }}
        <span v-if="item.source_decision_id">
          · 当次决策版本 {{ item.source_decision_revision }}</span
        >
        <RouterLink
          v-if="item.source_decision_id"
          :to="{
            name: 'ProjectInspectionBoardComp',
            params: { project_id: projectId },
            query: { decision_id: item.source_decision_id }
          }"
          >查看决策历史</RouterLink
        >
        <a-button
          v-if="item.dispatch_state === 'dispatched'"
          size="small"
          :disabled="busy"
          @click="refresh(item)"
          >查状态</a-button
        >
        <a-button
          v-if="
            item.dispatch_state === 'dispatched' &&
            ['completed', 'failed', 'cancelled'].includes(item.remote_status)
          "
          size="small"
          :disabled="busy"
          @click="collect(item)"
          >回收结果</a-button
        >
        <p v-if="item.error_code">{{ item.error_code }}</p>
        <p v-if="item.result?.summary">{{ item.result.summary }}</p>
        <p v-if="item.artifact_path">产物：{{ item.artifact_path }}</p>
      </li>
    </ul>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { formatDateTime } from '@/utils/time'
import { RouterLink } from 'vue-router'
import { projectWorkApi } from '@/apis/project_work_api'
import { governanceBoardApi } from '@/apis/governance_board_api'
const props = defineProps({
  projectId: String,
  taskId: String,
  title: String,
  description: String,
  ended: Boolean,
  agents: { type: Array, default: () => [] }
})
const items = ref([]),
  agentSlug = ref(),
  executor = ref('codex'),
  error = ref(''),
  busy = ref(false),
  loading = ref(false)
let generation = 0
const enabled = computed(() => {
  const agent = props.agents.find((a) => a.slug === agentSlug.value)
  const coding = { ...agent?.config_json?.coding, ...agent?.config_overrides?.coding }
  return Array.isArray(coding.executors)
    ? coding.executors.filter((key) => ['codex', 'opencode'].includes(key))
    : []
})
function statusLabel(status) {
  return (
    {
      pending: '待投递',
      dispatched: '已投递',
      collecting: '回收中',
      reclaimed: '已回收',
      running: '执行中',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消'
    }[status] || status
  )
}
async function load() {
  const seq = ++generation,
    project = props.projectId,
    task = props.taskId
  loading.value = true
  try {
    const result = await projectWorkApi.listDelegations(project)
    if (seq === generation) items.value = result.filter((item) => item.work_task_id === task)
  } catch (e) {
    if (seq === generation) error.value = e?.message || '读取委派失败'
  } finally {
    if (seq === generation) loading.value = false
  }
}
async function act(action) {
  if (busy.value) return
  const project = props.projectId,
    task = props.taskId
  busy.value = true
  error.value = ''
  try {
    await action()
    if (project === props.projectId && task === props.taskId) await load()
  } catch (e) {
    if (project === props.projectId && task === props.taskId)
      error.value = e?.message || '委派失败，选择已保留'
  } finally {
    if (project === props.projectId && task === props.taskId) busy.value = false
  }
}
const dispatch = () =>
  act(() =>
    executor.value === 'multica'
      ? governanceBoardApi.createDelegation(props.projectId, {
          executor_key: 'multica',
          work_task_id: props.taskId,
          task: [props.title, props.description].filter(Boolean).join('\n\n')
        })
      : projectWorkApi.delegateTask(props.projectId, props.taskId, {
          executor_key: executor.value,
          agent_slug: agentSlug.value
        })
  )
const refresh = (item) =>
  act(() => governanceBoardApi.getDelegation(props.projectId, item.operation_id))
const collect = (item) =>
  act(() => governanceBoardApi.collectDelegation(props.projectId, item.operation_id))
watch(
  () => [props.projectId, props.taskId],
  () => {
    items.value = []
    agentSlug.value = undefined
    busy.value = false
    error.value = ''
    void load()
  },
  { immediate: true }
)
</script>
<style scoped>
.delegation-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}
.delegation-controls :deep(.ant-select) {
  min-width: 180px;
}
li {
  padding: 12px 0;
  overflow-wrap: anywhere;
}
a {
  color: var(--main-color);
}
</style>
