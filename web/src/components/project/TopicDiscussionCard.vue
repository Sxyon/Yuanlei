<template>
  <section class="discussion-card" :id="`topic-comment-${comment.id}`">
    <p>
      {{ comment.author_name }} · {{ timestamp(comment.created_at) }} · 议题修订
      {{ comment.revision_number || '未知' }}
    </p>
    <MarkdownPreview :content="comment.content" />
    <template v-if="currentDisposition">
      <a-tag
        >{{ labels[currentDisposition.disposition] }} · 处置版本
        {{ currentDisposition.version }}</a-tag
      >
      <p>{{ currentDisposition.explanation }}</p>
      <router-link
        v-if="currentDisposition.reference_snapshot"
        :to="currentDisposition.reference_snapshot.href"
        >查看实际去向 · {{ referenceLabel(currentDisposition.reference_snapshot) }}</router-link
      >
      <p v-else class="hint">尚未关联去向</p>
      <details>
        <summary>处理历史</summary>
        <article v-for="record in comment.dispositions" :key="record.id">
          <p>
            {{ labels[record.disposition] }} · 版本 {{ record.version }} ·
            {{ record.author_name }} · {{ timestamp(record.created_at) }}
          </p>
          <p>{{ record.explanation }}</p>
          <router-link v-if="record.reference_snapshot" :to="record.reference_snapshot.href">{{
            referenceLabel(record.reference_snapshot)
          }}</router-link>
          <p v-else>尚未关联去向</p>
          <details v-if="record.reference_snapshot">
            <summary>引用时快照</summary>
            <MarkdownPreview :content="snapshotText(record.reference_snapshot)" />
          </details>
        </article>
      </details>
    </template>
    <p v-else class="hint">尚未处置</p>
    <article v-for="reply in comment.replies || []" :key="reply.id" class="reply">
      <p>
        {{ reply.author_name }} · {{ timestamp(reply.created_at) }} · 发布时议题修订
        {{ reply.revision_number || '未知' }}
      </p>
      <MarkdownPreview :content="reply.content" />
    </article>
    <template v-if="!archived">
      <div class="actions">
        <a-button @click="replyOpen = !replyOpen">回复</a-button
        ><a-button @click="openDisposition">记录处理</a-button>
      </div>
      <div v-if="replyOpen" class="record-form">
        <p>回复 {{ comment.author_name }} 的讨论（仅一层回复）</p>
        <a-textarea
          v-model:value="replyDraft.content"
          aria-label="回复内容"
          :maxlength="100000"
          :auto-size="{ minRows: 3, maxRows: 12 }"
        />
        <a-button :disabled="busy || !replyDraft.content.trim()" @click="postReply"
          >发布回复</a-button
        >
      </div>
      <div v-if="dispositionOpen" class="record-form">
        <a-button :disabled="busy" @click="discardDisposition">清弃处置草稿并重新核对</a-button>
        <a-select v-model:value="dispositionDraft.disposition" aria-label="采纳处置"
          ><a-select-option v-for="(label, key) in labels" :key="key" :value="key">{{
            label
          }}</a-select-option></a-select
        >
        <a-textarea
          v-model:value="dispositionDraft.explanation"
          aria-label="处置说明"
          placeholder="处理说明（必填）"
          :maxlength="100000"
        />
        <a-select
          v-model:value="dispositionDraft.referenceKey"
          allow-clear
          aria-label="实际去向"
          placeholder="选择实际去向（可选）"
          show-search
          option-filter-prop="label"
        >
          <a-select-option
            v-for="candidate in candidates"
            :key="candidateKey(candidate)"
            :value="candidateKey(candidate)"
            :label="candidateTitle(candidate)"
            >{{ candidateTitle(candidate) }}</a-select-option
          >
        </a-select>
        <p>没有实际去向时会记录“尚未关联去向”。选择决策不代表批准，选择结果不改变验收。</p>
        <a-button :disabled="busy || !dispositionDraft.explanation.trim()" @click="saveDisposition"
          >保存处置</a-button
        >
      </div>
    </template>
    <a-alert v-if="error" type="error" show-icon :message="error" />
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { describeBoardError } from '@/utils/governanceBoard'
import {
  candidateKey,
  candidateTitle,
  referenceLabel,
  snapshotText,
  selectedReference,
  consumeIntent,
  stableIntent
} from '@/utils/topicFollowup'

const props = defineProps({
  projectId: String,
  topicId: String,
  comment: Object,
  candidates: Array,
  archived: Boolean,
  draft: Object
})
const emit = defineEmits(['updated', 'visibility-lost'])
const sharedDraft = reactive(props.draft)
const replyOpen = ref(false),
  dispositionOpen = ref(false),
  busy = ref(false),
  error = ref('')
sharedDraft.replies ||= {}
sharedDraft.replies[props.comment.id] ||= { content: '' }
const replyDraft = sharedDraft.replies[props.comment.id]
sharedDraft.dispositions ||= {}
sharedDraft.dispositions[props.comment.id] ||= {
  disposition: 'adopted',
  explanation: '',
  referenceKey: undefined
}
// 按议题/讨论持有草稿，卸载后迟到响应不清空草稿。
const dispositionDraft = sharedDraft.dispositions[props.comment.id]
let active = true
onBeforeUnmount(() => {
  active = false
})
const currentDisposition = computed(() => props.comment.dispositions?.[0])
const labels = { adopted: '采纳', partial: '部分采纳', rejected: '不采纳' }
const timestamp = (raw) => (raw ? new Date(raw).toLocaleString('zh-CN') : '')
async function postReply() {
  const content = replyDraft.content
  const options = stableIntent(replyDraft, { parent_comment_id: props.comment.id, content })
  busy.value = true
  error.value = ''
  try {
    await api.createTopicComment(props.projectId, props.topicId, content, 'discussion', {
      parent_comment_id: props.comment.id,
      operation_id: options.operation_id
    })
    if (!active) return
    consumeIntent(replyDraft, options.operation_id)
    if (replyDraft.content === content) replyDraft.content = ''
    emit('updated')
  } catch (failure) {
    if (active) {
      error.value = describeBoardError(failure)
      if ([401, 403, 404].includes(failure?.status || failure?.response?.status)) emit('visibility-lost', failure)
    }
  } finally {
    if (active) busy.value = false
  }
}
function openDisposition() {
  if (!dispositionDraft.explanation && !dispositionDraft.referenceKey && !dispositionDraft.intent)
    dispositionDraft.expectedVersion = currentDisposition.value?.version || 0
  dispositionOpen.value = !dispositionOpen.value
  error.value = dispositionDraft.expectedVersion !== (currentDisposition.value?.version || 0)
    ? '保留原处置版本的草稿；请核对当前记录，或清弃草稿后重新起草。' : ''
}
function discardDisposition() {
  dispositionDraft.explanation = ''
  dispositionDraft.referenceKey = undefined
  delete dispositionDraft.intent
  delete dispositionDraft.operationId
  dispositionDraft.expectedVersion = currentDisposition.value?.version || 0
  error.value = ''
}
async function saveDisposition() {
  const payload = stableIntent(dispositionDraft, {
    disposition: dispositionDraft.disposition,
    explanation: dispositionDraft.explanation,
    reference: selectedReference(dispositionDraft.referenceKey),
    expected_version: dispositionDraft.expectedVersion
  })
  busy.value = true
  error.value = ''
  try {
    await api.recordTopicDisposition(props.projectId, props.topicId, props.comment.id, payload)
    if (!active) return
    consumeIntent(dispositionDraft, payload.operation_id)
    if (dispositionDraft.disposition === payload.disposition && dispositionDraft.explanation === payload.explanation && JSON.stringify(selectedReference(dispositionDraft.referenceKey)) === JSON.stringify(payload.reference)) { dispositionDraft.explanation = ''; dispositionDraft.referenceKey = undefined }
    dispositionOpen.value = false
    emit('updated')
  } catch (failure) {
    if (active) {
      error.value = describeBoardError(failure)
      if ([401, 403, 404].includes(failure?.status || failure?.response?.status)) emit('visibility-lost', failure)
    }
  } finally {
    if (active) busy.value = false
  }
}
</script>

<style scoped>
.discussion-card,
.record-form {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.reply {
  margin-left: 16px;
  border-left: 2px solid var(--gray-150);
  padding-left: 12px;
}
.actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
a {
  color: var(--main-color);
}
.hint {
  color: var(--color-text-secondary);
}
</style>
