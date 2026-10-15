<template>
  <div class="resource-panel">
    <header v-if="mode === 'activity'" class="repository-review-heading"><strong>{{ resource.alias }}</strong><LoaderCircle :size="14" class="repository-loading" :class="{ spinning: liveLoading }" :aria-label="liveLoading ? '正在刷新仓库改动' : undefined" :aria-hidden="!liveLoading" /></header>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-form v-if="mode !== 'activity'" layout="vertical" class="resource-grid">
      <a-form-item label="项目目录" required>
        <a-input v-model:value="draft.checkout_path" :disabled="!!resource.checkout_head_sha" placeholder="相对于项目空间，例如 backend" />
      </a-form-item>
      <a-form-item label="检出分支" required>
        <a-select v-model:value="draft.branch" :disabled="!!resource.checkout_head_sha" :loading="loadingBranches" @focus="loadBranches">
          <a-select-option v-for="branch in branches" :key="branch.name" :value="branch.name">{{ branch.name }}</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item><template #label>使用模式<a-tooltip :title="draft.usage_mode === 'in_place' ? '直接使用项目目录；任务持续占用，同一目录排队执行。' : '任务在独立工作树中执行，项目目录保留选定分支。'" :trigger="['hover','focus']"><button type="button" class="resource-help-button" aria-label="使用模式说明">?</button></a-tooltip></template>
        <a-select v-model:value="draft.usage_mode">
          <a-select-option value="in_place">直接修改这个文件夹</a-select-option>
          <a-select-option value="worktree">并行隔离运行</a-select-option>
        </a-select>
      </a-form-item>
      <a-form-item><template #label>授权模式<a-tooltip title="受保护目标需人工批准；自动授权及任务分支的批准依据可在历史记录中查看。修改授权模式不会自动提交或合并。" :trigger="['hover','focus']"><button type="button" class="resource-help-button" aria-label="授权模式说明">?</button></a-tooltip></template>
        <a-select v-model:value="draft.approval_mode">
          <a-select-option value="protected">受保护：人工提交与合并</a-select-option>
          <a-select-option value="automatic">自动授权（保留批准记录）</a-select-option>
        </a-select>
      </a-form-item>
    </a-form>
    <div class="resource-actions">
      <a-button v-if="mode !== 'activity'" :disabled="resource.status !== 'active'" :loading="busy === 'configure'" @click="configure">保存资源配置</a-button>
      <a-button v-if="!resource.checkout_head_sha && resource.status === 'active'" :disabled="!resource.checkout_path" :loading="busy === 'checkout'" @click="checkout">检出分支内容</a-button>
      <a-button v-if="mode === 'full' && (resource.checkout_head_sha || resource.status === 'provision_failed')" :loading="busy === 'review'" @click="openReview">查看改动与提交</a-button>
    </div>
    <div v-if="mode === 'full'" class="resource-occupancies">
      <a-button size="small" :loading="busy === 'occupancies'" @click="loadOccupancies">刷新资源使用情况</a-button>
      <div v-for="slot in occupancies" :key="slot.id" class="resource-actions">
        <a-tag :color="slot.status === 'queued' ? 'orange' : 'blue'">{{ slot.status === 'queued' ? '排队等待' : '持续占用' }}</a-tag>
        <span>{{ slot.scope_key }} · {{ slot.run_status || '等待运行' }}</span>
        <a-popconfirm title="确认释放占用？正在执行或存在未提交内容时将拒绝释放。" @confirm="release(slot)">
          <a-button size="small" :disabled="!!busy">释放占用</a-button>
        </a-popconfirm>
      </div>
    </div>
    <template v-if="mode !== 'configure'">
      <div v-if="mode === 'activity' && (liveError || review && liveReview && (review.head_sha !== liveReview.head_sha || review.tree_sha !== liveReview.tree_sha))" class="live-resource-summary"><span v-if="liveError" role="alert">{{ liveError }}</span><span v-if="review && liveReview && (review.head_sha !== liveReview.head_sha || review.tree_sha !== liveReview.tree_sha)">有新改动，刷新差异后再确认操作</span></div>
    </template>
    <a-modal v-model:open="pullOpen" title="合并请求" width="850px" :footer="null"><GitPullRequestPanel v-if="pullOpen" :project-id="projectId" :resource="resource" /></a-modal>
    <component :is="mode === 'activity' ? 'section' : 'a-modal'" v-model:open="reviewOpen" title="审查项目资源改动" width="900px" :footer="null" :class="{ 'inline-review': mode === 'activity' }">
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <template v-if="review">
        <a-alert v-if="review.incomplete_checkout" type="warning" show-icon message="检出尚未完成：可查看并恢复未提交内容，再重试初始化；暂不能提交。" />
        <p>{{ review.branch }} · HEAD {{ review.head_sha?.slice(0, 12) }}</p>
        <div class="git-state"><a-tag :color="review.dirty ? 'orange' : 'green'">{{ review.dirty ? '存在未提交改动' : '没有未提交改动' }}</a-tag>
        <a-tag v-if="review.unpushed" color="orange">本地提交尚未同步</a-tag>
        <span v-if="!review.diff" class="clean-workspace">工作区与 HEAD 一致</span></div>
        <pre v-if="review.diff" class="git-diff">{{ review.diff }}</pre>
        <a-textarea v-if="review.dirty && !review.incomplete_checkout" v-model:value="commitMessage" :rows="2" maxlength="2000" placeholder="提交说明" />
        <div class="resource-actions">
          <a-button :loading="busy === 'review'" @click="openReview">刷新差异</a-button>
          <a-popconfirm v-if="review.dirty && !review.incomplete_checkout" title="确认将当前审查的全部改动提交到此分支？" @open-change="open => confirmation = open ? 'commit' : confirmation === 'commit' ? '' : confirmation" @confirm="commit">
            <a-button type="primary" :loading="busy === 'commit'" :disabled="review.incomplete_checkout || !review.dirty || !commitMessage.trim()">确认提交</a-button>
          </a-popconfirm>
          <a-popconfirm title="确认将审查中的精确 HEAD 推送到资源分支？不会强制覆盖远端进展。" @open-change="open => confirmation = open ? 'push' : confirmation === 'push' ? '' : confirmation" @confirm="push">
            <a-button :loading="busy === 'push'" :disabled="review.incomplete_checkout || review.dirty || !!busy">确认推送</a-button>
          </a-popconfirm>
          <a-popconfirm title="确认丢弃审查中显示的全部未提交改动？此操作无法撤销。" @open-change="open => confirmation = open ? 'discard' : confirmation === 'discard' ? '' : confirmation" @confirm="discard">
            <a-button danger :loading="busy === 'discard'" :disabled="!review.dirty || !!busy">丢弃未提交改动</a-button>
          </a-popconfirm>
          <a-button @click="pullOpen = true">发起合并请求</a-button>
        </div>
      </template>
    </component>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { LoaderCircle } from '@lucide/vue'
import { projectApi } from '@/apis/project_api'
import GitPullRequestPanel from './GitPullRequestPanel.vue'

const props = defineProps({ projectId: { type: String, required: true }, resource: { type: Object, required: true }, mode: { type: String, default: 'full' }, refreshToken: { type: Number, default: 0 } })
const emit = defineEmits(['updated'])
const draft = reactive({})
const branches = ref([])
const loadingBranches = ref(false)
const busy = ref('')
const error = ref('')
const review = ref(null)
const reviewOpen = ref(false)
const commitMessage = ref('')
const confirmation = ref('')
const occupancies = ref([])
const pullOpen = ref(false), liveReview = ref(null), liveLoading = ref(false), liveError = ref('')
let liveSequence = 0
/** 实时投影不覆盖确认弹窗中的冻结HEAD/tree与输入。 */
async function refreshLive() {
  if (props.mode !== 'activity' || (!props.resource.checkout_head_sha && props.resource.status !== 'provision_failed') || liveLoading.value) return
  const version = generation, sequence = ++liveSequence
  liveLoading.value = true
  try {
    const result = await projectApi.reviewGitResource(props.projectId, props.resource.id)
    if (version === generation && sequence === liveSequence) { liveReview.value = result; liveError.value = ''; if (!review.value || (!review.value.dirty && !review.value.unpushed && !commitMessage.value && !busy.value && !confirmation.value)) review.value = result }
  } catch (cause) { if (version === generation && sequence === liveSequence) liveError.value = cause.message || '改动刷新失败' }
  finally { if (version === generation && sequence === liveSequence) liveLoading.value = false }
}
let generation = 0
watch([() => props.projectId, () => props.resource.id], () => {
  generation++
  liveSequence++; liveReview.value = null; liveError.value = ''; liveLoading.value = false; pullOpen.value = false
  reviewOpen.value = false
  confirmation.value = ''
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
watch(() => [props.projectId, props.resource.id, props.resource.checkout_head_sha, props.refreshToken], refreshLive, { immediate: true })
onBeforeUnmount(() => { generation++; liveSequence++ })
</script>

<style scoped>
.resource-panel { margin-top: 12px; width: 100%; }
.resource-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 12px; }
.resource-help { color: var(--text-secondary); font-size: 12px; }
.resource-actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.inline-review { margin-top:14px; }.inline-review .git-diff { max-height:none; overflow:visible; }.git-diff { max-height: 420px; overflow: auto; background: var(--bg-secondary); padding: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 640px) { .resource-grid { grid-template-columns: 1fr; } }
.resource-help-button { border:0; border-radius:50%; background:transparent; color:var(--color-text-secondary); cursor:help; margin-left:5px; padding:0 4px; }.resource-help-button:focus-visible { outline:2px solid var(--main-color); }
.live-resource-summary { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin:12px 0; font-size:12px; color:var(--color-text-secondary); }.live-resource-diff { margin:12px 0; padding:12px; background:var(--gray-50); font-size:12px; white-space:pre-wrap; overflow-wrap:anywhere; }
.repository-review-heading { display:flex; align-items:center; gap:8px; min-height:22px; }.repository-loading { visibility:hidden; color:var(--color-text-secondary); flex-shrink:0; }.repository-loading.spinning { visibility:visible; animation:repository-spin 1s linear infinite; }@keyframes repository-spin { to { transform:rotate(360deg); } }
.git-state { display:flex; align-items:center; flex-wrap:wrap; gap:8px; margin-bottom:12px; }.clean-workspace { font-size:12px; color:var(--color-text-secondary); }.resource-actions :deep(.ant-btn-primary:not(:disabled)) { color:#fff; }.resource-actions :deep(.ant-btn-primary:disabled) { color:var(--gray-600); background:var(--gray-100); opacity:1; }
</style>
