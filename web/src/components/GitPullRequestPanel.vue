<template>
  <a-collapse class="pull-request-panel">
    <a-collapse-panel key="pulls" header="Gitea 合并请求">
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <div class="pull-actions">
        <a-button :loading="busy" @click="refresh">刷新合并请求与任务分支</a-button>
      </div>
      <a-form layout="vertical">
        <a-form-item label="源任务分支">
          <a-select v-model:value="draft.head_branch" :disabled="busy" placeholder="选择已推送的任务分支">
            <a-select-option v-for="branch in pushedBranches" :key="branch" :value="branch">{{ branch }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="目标分支">
          <a-select v-model:value="draft.base_branch" :disabled="busy">
            <a-select-option v-for="branch in targetBranches" :key="branch" :value="branch">{{ branch }}</a-select-option>
          </a-select>
        </a-form-item>
        <a-form-item label="标题"><a-input v-model:value="draft.title" maxlength="255" :disabled="busy" /></a-form-item>
        <a-form-item label="说明"><a-textarea v-model:value="draft.body" :rows="2" maxlength="10000" :disabled="busy" /></a-form-item>
        <a-button :loading="busy" :disabled="!draft.head_branch || !draft.title.trim() || draft.head_branch === draft.base_branch" @click="create">创建 Gitea 合并请求</a-button>
      </a-form>
      <a-empty v-if="loaded && !pulls.length" description="暂无任务合并请求" />
      <p v-if="pulls.some((pull) => !pull.merged && pull.state === 'open')">合并前会检查目标状态；检查后其他人推送的目标更新仍可能进入本次合并。</p>
      <div v-for="pull in pulls" :key="pull.number" class="pull-item">
        <p>#{{ pull.number }} {{ pull.title }}</p>
        <p>{{ pull.head_branch }} → {{ pull.base_branch }}</p>
        <p>源 {{ pull.head_sha.slice(0, 12) }} · 目标 {{ pull.base_sha.slice(0, 12) }}</p>
        <div class="pull-actions">
          <a-tag :color="pull.merged ? 'green' : 'blue'">{{ pull.merged ? '已合并' : pull.state === 'open' ? '待合并' : '已关闭' }}</a-tag>
          <a :href="pull.url" target="_blank" rel="noopener noreferrer">在 Gitea 查看</a>
          <a-popconfirm v-if="!pull.merged && pull.state === 'open'" title="确认将此源提交实际合并到目标分支？源提交变化时会拒绝操作。" @confirm="merge(pull)">
            <a-button type="primary" :disabled="busy || pull.mergeable !== true">确认并执行合并</a-button>
          </a-popconfirm>
        </div>
      </div>
    </a-collapse-panel>
  </a-collapse>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { projectApi } from '@/apis/project_api'

const props = defineProps({ projectId: { type: String, required: true }, resource: { type: Object, required: true } })
const busy = ref(false)
const error = ref('')
const loaded = ref(false)
const pulls = ref([])
const worktrees = ref([])
const draft = reactive({ head_branch: '', base_branch: '', title: '', body: '' })
const pushedBranches = computed(() => worktrees.value.filter((value) => value.last_pushed_sha && value.branch !== draft.base_branch).map((value) => value.branch))
const targetBranches = computed(() => [...new Set([props.resource.configured_base_branch || props.resource.default_branch, ...worktrees.value.map((value) => value.branch)])].filter(Boolean))
let generation = 0
watch([() => props.projectId, () => props.resource.id], () => {
  generation++
  busy.value = false
  error.value = ''
  loaded.value = false
  pulls.value = []
  worktrees.value = []
  Object.assign(draft, { head_branch: '', base_branch: props.resource.configured_base_branch || props.resource.default_branch, title: '', body: '' })
}, { immediate: true })
const perform = async (call) => {
  if (busy.value) return
  const version = generation
  const projectId = props.projectId
  const resourceId = props.resource.id
  busy.value = true
  error.value = ''
  try {
    await call(projectId, resourceId, version)
  } catch (failure) {
    if (version === generation) error.value = failure?.message || 'Gitea 操作失败'
  } finally {
    if (version === generation) busy.value = false
  }
}
const refresh = () => perform(async (projectId, resourceId, version) => {
  const [values, allocations] = await Promise.all([projectApi.getGitPullRequests(projectId, resourceId), projectApi.getGitWorktrees(projectId)])
  if (version !== generation) return
  pulls.value = values
  worktrees.value = allocations.filter((value) => value.repository_id === resourceId)
  loaded.value = true
})
const create = () => {
  const payload = { ...draft }
  return perform(async (projectId, resourceId, version) => {
    const value = await projectApi.createGitPullRequest(projectId, resourceId, payload)
    if (version !== generation) return
    pulls.value = [value, ...pulls.value.filter((pull) => pull.number !== value.number)]
    loaded.value = true
    message.success('Gitea 合并请求已创建')
  })
}
const merge = (pull) => perform(async (projectId, resourceId, version) => {
  const value = await projectApi.mergeGitPullRequest(projectId, resourceId, pull.number, { expected_head: pull.head_sha, expected_base: pull.base_sha })
  if (version !== generation) return
  pulls.value = pulls.value.map((item) => item.number === value.number ? value : item)
  message.success('Gitea 已确认合并完成')
})
</script>

<style scoped>
.pull-request-panel { margin-top: 12px; }
.pull-actions { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.pull-item { padding: 12px 0; border-top: 1px solid var(--border-color); overflow-wrap: anywhere; }
</style>
