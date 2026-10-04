<template>
  <div class="worktree-artifacts">
    <a-button :disabled="worktree.status !== 'ready'" :loading="busy === 'review'" @click="openReview">查看改动与提交</a-button>
    <a-modal v-model:open="open" title="审查任务工作树成果" width="900px" :footer="null">
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <template v-if="review">
        <p>{{ review.branch }} · HEAD {{ review.head_sha?.slice(0, 12) }}</p>
        <a-tag :color="review.dirty ? 'orange' : 'green'">{{ review.dirty ? '存在未提交改动' : '没有未提交改动' }}</a-tag>
        <a-tag v-if="review.unpushed" color="orange">本地提交尚未同步</a-tag>
        <template v-if="review.committed_diff">
          <p>已提交成果（自上次推送或任务基线以来）</p>
          <pre>{{ review.committed_diff }}</pre>
        </template>
        <p>未提交改动</p>
        <pre>{{ review.diff || '工作树与 HEAD 一致' }}</pre>
        <a-textarea v-model:value="commitMessage" :rows="2" maxlength="2000" placeholder="提交说明" />
        <div class="actions">
          <a-button :disabled="!!busy" @click="openReview">刷新差异</a-button>
          <a-popconfirm title="确认将审查中的全部改动提交到此任务分支？" @confirm="operate('commit')">
            <a-button type="primary" :disabled="!!busy || !review.dirty || !commitMessage.trim()">确认提交</a-button>
          </a-popconfirm>
          <a-popconfirm title="确认推送审查中的精确 HEAD？不会强制覆盖远端。" @confirm="operate('push')">
            <a-button :disabled="!!busy || review.dirty">确认推送</a-button>
          </a-popconfirm>
          <a-popconfirm title="确认丢弃审查中的未提交改动？无法撤销，忽略文件将保留。" @confirm="operate('discard')">
            <a-button danger :disabled="!!busy || !review.dirty">丢弃未提交改动</a-button>
          </a-popconfirm>
        </div>
      </template>
    </a-modal>
  </div>
</template>
<script setup>
import { ref, watch } from 'vue'
import { projectApi } from '@/apis/project_api'
const props = defineProps({ projectId: { type: String, required: true }, worktree: { type: Object, required: true } })
const emit = defineEmits(['updated'])
const open = ref(false), review = ref(null), error = ref(''), busy = ref(''), commitMessage = ref('')
let generation = 0
watch([() => props.projectId, () => props.worktree.id], () => {
  generation++
  open.value = false
  review.value = null
  error.value = ''
  busy.value = ''
  commitMessage.value = ''
})
const request = async (action, payload) => {
  if (busy.value) return
  const version = generation
  busy.value = action
  error.value = ''
  try {
    const methods = { review: 'reviewGitWorktree', commit: 'commitGitWorktree', push: 'pushGitWorktree', discard: 'discardGitWorktree' }
    const result = await projectApi[methods[action]](props.projectId, props.worktree.id, payload)
    if (version !== generation) return
    review.value = result
    open.value = true
    if (action !== 'review') {
      commitMessage.value = ''
      emit('updated')
    }
  } catch (failure) {
    if (version === generation) { error.value = failure?.message || '工作树操作失败，请刷新后重试'; open.value = true }
  } finally {
    if (version === generation) busy.value = ''
  }
}
const openReview = () => request('review')
const operate = (action) => {
  if (!review.value || busy.value) return
  if (action === 'commit' && (!review.value.dirty || !commitMessage.value.trim())) return
  if (action === 'push' && review.value.dirty) return
  if (action === 'discard' && !review.value.dirty) return
  const payload = { expected_head: review.value.head_sha, expected_tree: review.value.tree_sha }
  if (action === 'commit') payload.message = commitMessage.value.trim()
  return request(action, payload)
}
</script>
<style scoped>
.worktree-artifacts { grid-column: 1 / -1; }
pre { max-height: 420px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; padding: 12px; background: var(--bg-secondary); }
.actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
</style>
