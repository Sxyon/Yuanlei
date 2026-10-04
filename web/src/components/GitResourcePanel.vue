<template>
  <div class="resource-panel">
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-form layout="vertical" class="resource-grid">
      <a-form-item label="项目目录" required>
        <a-input v-model:value="draft.checkout_path" :disabled="!!resource.checkout_head_sha" placeholder="相对于项目空间，例如 backend" />
      </a-form-item>
      <a-form-item label="检出分支" required>
        <a-select v-model:value="draft.branch" :disabled="!!resource.checkout_head_sha" :loading="loadingBranches" @focus="loadBranches">
          <a-select-option v-for="branch in branches" :key="branch.name" :value="branch.name">{{ branch.name }}</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="使用模式">
        <a-select v-model:value="draft.usage_mode">
          <a-select-option value="in_place">直接修改这个文件夹</a-select-option>
          <a-select-option value="worktree">并行隔离运行</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item label="授权模式">
        <a-select v-model:value="draft.approval_mode">
          <a-select-option value="protected">受保护：人工提交与合并</a-select-option>
          <a-select-option value="automatic">自动授权（保留批准记录）</a-select-option>
        </a-select>
      </a-form-item>
    </a-form>
    <p>受保护资源目标由人工批准；自动授权和任务分支批准依据可在“审批与历史”查看。授权模式不会自动触发提交或合并。</p>
    <p class="resource-help">{{ draft.usage_mode === 'in_place' ? '任务直接修改项目资源目录，持续占用并排队使用。' : '任务在独立工作树中修改，项目资源目录用于展示选定分支。' }}</p>
    <div class="resource-actions">
      <a-button :disabled="resource.status !== 'active'" :loading="busy === 'configure'" @click="configure">保存资源配置</a-button>
      <a-button v-if="!resource.checkout_head_sha && resource.status === 'active'" :disabled="!resource.checkout_path" :loading="busy === 'checkout'" @click="checkout">检出分支内容</a-button>
      <a-button v-if="resource.checkout_head_sha || resource.status === 'provision_failed'" :loading="busy === 'review'" @click="openReview">查看改动与提交</a-button>
    </div>
    <div class="resource-occupancies">
      <a-button size="small" :loading="busy === 'occupancies'" @click="loadOccupancies">刷新资源使用情况</a-button>
      <div v-for="slot in occupancies" :key="slot.id" class="resource-actions">
        <a-tag :color="slot.status === 'queued' ? 'orange' : 'blue'">{{ slot.status === 'queued' ? '排队等待' : '持续占用' }}</a-tag>
        <span>{{ slot.scope_key }} · {{ slot.run_status || '等待运行' }}</span>
        <a-popconfirm title="确认释放占用？正在执行或存在未提交内容时将拒绝释放。" @confirm="release(slot)">
          <a-button size="small" :disabled="!!busy">释放占用</a-button>
        </a-popconfirm>
      </div>
    </div>
    <GitPullRequestPanel :project-id="projectId" :resource="resource" />
    <a-modal v-model:open="reviewOpen" title="审查项目资源改动" width="900px" :footer="null">
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <template v-if="review">
        <a-alert v-if="review.incomplete_checkout" type="warning" show-icon message="检出尚未完成：可查看并恢复未提交内容，再重试初始化；暂不能提交。" />
        <p>{{ review.branch }} · HEAD {{ review.head_sha?.slice(0, 12) }}</p>
        <a-tag :color="review.dirty ? 'orange' : 'green'">{{ review.dirty ? '存在未提交改动' : '没有未提交改动' }}</a-tag>
        <a-tag v-if="review.unpushed" color="orange">本地提交尚未同步</a-tag>
        <pre class="git-diff">{{ review.diff || '工作区与 HEAD 一致' }}</pre>
        <a-textarea v-model:value="commitMessage" :rows="2" maxlength="2000" placeholder="提交说明" />
        <div class="resource-actions">
          <a-button :loading="busy === 'review'" @click="openReview">刷新差异</a-button>
          <a-popconfirm title="确认将当前审查的全部改动提交到此分支？" @confirm="commit">
            <a-button type="primary" :loading="busy === 'commit'" :disabled="review.incomplete_checkout || !review.dirty || !commitMessage.trim()">确认提交</a-button>
          </a-popconfirm>
          <a-popconfirm title="确认将审查中的精确 HEAD 推送到资源分支？不会强制覆盖远端进展。" @confirm="push">
            <a-button :loading="busy === 'push'" :disabled="review.incomplete_checkout || review.dirty || !!busy">确认推送</a-button>
          </a-popconfirm>
          <a-popconfirm title="确认丢弃审查中显示的全部未提交改动？此操作无法撤销。" @confirm="discard">
            <a-button danger :loading="busy === 'discard'" :disabled="!review.dirty || !!busy">丢弃未提交改动</a-button>
          </a-popconfirm>
        </div>
      </template>
    </a-modal>
  </div>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { projectApi } from '@/apis/project_api'
import GitPullRequestPanel from './GitPullRequestPanel.vue'

const props = defineProps({ projectId: { type: String, required: true }, resource: { type: Object, required: true } })
const emit = defineEmits(['updated'])
const draft = reactive({})
const branches = ref([])
const loadingBranches = ref(false)
const busy = ref('')
const error = ref('')
const review = ref(null)
const reviewOpen = ref(false)
const commitMessage = ref('')
const occupancies = ref([])
let generation = 0
watch([() => props.projectId, () => props.resource.id], () => {
  generation++
  reviewOpen.value = false
  review.value = null
  busy.value = ''
  loadingBranches.value = false
  occupancies.value = []
  error.value = ''
}, { immediate: true })
watch([() => props.projectId, () => props.resource.id, () => props.resource.checkout_path, () => props.resource.configured_base_branch, () => props.resource.default_branch, () => props.resource.usage_mode, () => props.resource.approval_mode], () => {
  const resource = props.resource
  Object.assign(draft, {
    checkout_path: resource.checkout_path || resource.repository_name,
    branch: resource.configured_base_branch || resource.default_branch,
    usage_mode: resource.usage_mode || 'worktree',
    approval_mode: resource.approval_mode || 'protected'
  })
  branches.value = draft.branch ? [{ name: draft.branch }] : []
}, { immediate: true })

const perform = async (action, call, finish) => {
  if (busy.value) return
  const version = generation
  busy.value = action
  error.value = ''
  try {
    const result = await call(props.projectId, props.resource.id)
    if (version === generation) finish?.(result)
  } catch (failure) {
    if (version === generation) error.value = failure?.message || 'Git 操作失败'
  } finally {
    if (version === generation) busy.value = ''
  }
}
const loadBranches = async () => {
  const version = generation
  loadingBranches.value = true
  try {
    const result = await projectApi.getRepositoryBranches(props.projectId, props.resource.id)
    if (version === generation) branches.value = result
  } catch (failure) {
    if (version === generation) error.value = failure?.message || '读取分支失败'
  } finally {
    if (version === generation) loadingBranches.value = false
  }
}
const configure = () => perform('configure', (projectId, resourceId) =>
  projectApi.configureGitResource(projectId, resourceId, { ...draft }), (result) => emit('updated', result))
const checkout = () => perform('checkout', projectApi.checkoutGitResource, (result) => {
  emit('updated', result)
  message.success('分支内容已检出到项目目录')
})
const openReview = () => perform('review', projectApi.reviewGitResource, (result) => {
  review.value = result
  reviewOpen.value = true
})
const loadOccupancies = () => perform('occupancies', (projectId) => projectApi.getGitOccupancies(projectId), (result) => {
  occupancies.value = result.filter((slot) => slot.repository_id === props.resource.id && slot.status !== 'released')
})
const release = (slot) => perform('release', (projectId, resourceId) =>
  projectApi.releaseGitResource(projectId, resourceId, slot.scope_key), () => {
    occupancies.value = occupancies.value.filter((value) => value.id !== slot.id)
    message.success('资源占用已释放')
  })
const discard = () => {
  if (!review.value?.dirty) return
  const payload = { expected_head: review.value.head_sha, expected_tree: review.value.tree_sha }
  return perform('discard', (projectId, resourceId) => projectApi.discardGitResource(projectId, resourceId, payload), (result) => {
    review.value = result
    message.success('未提交改动已清理')
  })
}

const push = () => {
  if (!review.value || review.value.dirty || review.value.incomplete_checkout) return
  const payload = { expected_head: review.value.head_sha, expected_tree: review.value.tree_sha }
  return perform('push', (projectId, resourceId) => projectApi.pushGitResource(projectId, resourceId, payload), (result) => {
    review.value = result
    message.success('远端 HEAD 已确认，资源提交已推送')
  })
}

const commit = () => {
  if (!review.value?.dirty || review.value.incomplete_checkout || !commitMessage.value.trim()) return
  const payload = { expected_head: review.value.head_sha, expected_tree: review.value.tree_sha, message: commitMessage.value.trim() }
  return perform('commit', (projectId, resourceId) => projectApi.commitGitResource(projectId, resourceId, payload), (result) => {
    review.value = result
    commitMessage.value = ''
    emit('updated', { ...props.resource, checkout_head_sha: result.head_sha })
    message.success('改动已提交')
  })
}
</script>

<style scoped>
.resource-panel { margin-top: 12px; width: 100%; }
.resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.resource-help { color: var(--text-secondary); font-size: 12px; }
.resource-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.git-diff { max-height: 420px; overflow: auto; background: var(--bg-secondary); padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 640px) { .resource-grid { grid-template-columns: 1fr; } }
</style>
