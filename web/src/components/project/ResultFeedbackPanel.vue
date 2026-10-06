<template>
  <div>
    <a-button @click="open('topic')">反馈到议题</a-button>
    <a-button @click="open('blueprint')">补入蓝图复盘</a-button>
    <p v-for="item in result.topic_feedbacks || []" :key="item.comment_id"><router-link :to="`/projects/${projectId}/inspection?topic_id=${item.topic_id}`">查看议题反馈 · 修订 {{ item.topic_revision }}</router-link></p>
    <a-modal v-model:open="visible" :title="mode === 'topic' ? '反馈到议题' : '蓝图复盘预览'" :confirm-loading="busy" :ok-button-props="{ disabled: !ready }" ok-text="确认保存" @ok="save">
      <p>请核对目标和文字后确认。反馈不会自动重开议题或改变工作状态。</p>
      <a-select v-model:value="target" :disabled="busy" aria-label="反馈目标" style="width: 100%" @change="selectTarget(false)">
        <a-select-option v-for="item in choices" :key="item.id || item.name" :value="item.id || item.name" :disabled="!!item.archived_at">{{ item.title || item.name }}{{ item.archived_at ? '（已归档，请先恢复）' : '' }}</a-select-option>
      </a-select>
      <a-select v-if="mode === 'topic'" v-model:value="discussionType" aria-label="反馈讨论类型"><a-select-option value="discussion">研讨</a-select-option><a-select-option value="correction">纠偏</a-select-option></a-select>
      <p v-if="shared">多个项目共用此工作目录，保存会影响共用文件。</p>
      <details v-if="comparison !== null"><summary>最新蓝图原文（请与保留草稿比较并合并）</summary><pre>{{ comparison }}</pre></details>
      <a-checkbox v-if="comparison !== null" v-model:checked="merged">已核对最新原文，并将需要保留的内容合入草稿</a-checkbox>
      <a-textarea v-model:value="content" :disabled="busy" aria-label="反馈预览正文" :rows="12" :maxlength="mode === 'topic' ? 100000 : 256000" />
      <a-button v-if="mode === 'blueprint' && target" @click="selectTarget(true)">刷新依据，保留本次草稿</a-button>
      <a-alert v-if="error" type="error" show-icon :message="error" />
    </a-modal>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { projectWorkApi } from '@/apis/project_work_api'
import { governanceBoardApi } from '@/apis/governance_board_api'
const props = defineProps({ projectId: { type: String, required: true }, taskId: { type: String, required: true }, taskNumber: { type: String, default: '' }, result: { type: Object, required: true } })
const emit = defineEmits(['refresh'])
const visible = ref(false), mode = ref('topic'), target = ref(), choices = ref([]), content = ref(''), discussionType = ref('discussion'), error = ref(''), busy = ref(false), shared = ref(false), preview = ref(null), comparison = ref(null), merged = ref(false)
let generation = 0, requestId = '', resultVersion = 0
onBeforeUnmount(() => { generation += 1 })
const ready = computed(() => (comparison.value === null || merged.value) && target.value && content.value.trim() && !busy.value && (mode.value === 'topic' || preview.value?.name === target.value))
async function open(kind) {
  const ticket = ++generation
  mode.value = kind; visible.value = true; target.value = undefined; preview.value = null; comparison.value = null; merged.value = false; error.value = ''; choices.value = []; shared.value = false
  requestId = crypto.randomUUID(); resultVersion = props.result.version
  content.value = `工作 ${props.taskNumber} · 结果 ${props.result.id}\n\n${props.result.summary}\n\n未解决事项：${props.result.unresolved || '未记录'}\n\n验收意见：${props.result.review_comment || '尚未验收'}`
  busy.value = true
  try {
    const data = await (kind === 'topic' ? governanceBoardApi.listTopics(props.projectId, true) : governanceBoardApi.listBlueprints(props.projectId))
    if (ticket !== generation) return
    choices.value = kind === 'topic' ? (Array.isArray(data) ? data : data.items || data.topics || []) : data.documents || []
    shared.value = !!data.shared_workdir
  } catch (failure) { if (ticket === generation) error.value = failure.message || '目标读取失败' }
  finally { if (ticket === generation) busy.value = false }
}
async function selectTarget(keepDraft = false) {
  requestId = crypto.randomUUID()
  if (mode.value !== 'blueprint') return
  const ticket = ++generation, name = target.value
  preview.value = null; busy.value = true; error.value = ''
  try {
    const data = await projectWorkApi.blueprintPreview(props.projectId, props.taskId, props.result.id, name)
    if (ticket !== generation) return
    preview.value = data; comparison.value = keepDraft ? data.original_content : null; merged.value = false; if (!keepDraft) content.value = data.content; resultVersion = data.result_version
  } catch (failure) { if (ticket === generation) error.value = failure.message || '预览失败，草稿保留' }
  finally { if (ticket === generation) busy.value = false }
}
async function save() {
  if (!ready.value) return
  const ticket = generation
  busy.value = true; error.value = ''
  try {
    const item = choices.value.find(row => row.id === target.value)
    if (mode.value === 'topic') {
      await projectWorkApi.topicFeedback(props.projectId, props.taskId, props.result.id, { topic_id: target.value, content: content.value, discussion_type: discussionType.value, request_id: requestId, expected_result_version: resultVersion, expected_topic_revision: item.revision_number })
    } else {
      await projectWorkApi.blueprintFeedback(props.projectId, props.taskId, props.result.id, { name: target.value, content: content.value, expected_hash: preview.value.content_hash, expected_identity: preview.value.file_identity, expected_result_version: resultVersion })
    }
    if (ticket !== generation) return
    visible.value = false; emit('refresh')
  } catch (failure) { if (ticket === generation) error.value = failure.message || '保存失败，草稿保留' }
  finally { if (ticket === generation) busy.value = false }
}
</script>
