<template>
  <section class="topic-outcome">
    <h4>预期结果 / 验证情况（可选）</h4>
    <MarkdownPreview v-if="topic.expected_outcome" :content="topic.expected_outcome" />
    <p v-else>未填写预期结果，问题型议题可以保持为空。</p>
    <MarkdownPreview
      v-if="topic.verification_conditions"
      :content="topic.verification_conditions"
    />
    <p v-else>未填写核对条件。</p>
    <p>现实达成由你明确确认；任务完成和工作结果被接受不会自动确认议题。</p>
    <a-alert
      v-if="conditionsChanged"
      type="warning"
      show-icon
      message="当前预期结果或核对条件已变化，旧确认只适用于记录时条件。"
    />
    <p v-if="!confirmations.length">尚未记录实际结果确认</p>
    <div v-if="!topic.archived_at" class="actions">
      <a-button @click="openForm('confirm')">记录实际达成</a-button>
      <a-button v-if="confirmations.length" @click="openForm('correct')">更正确认</a-button>
      <a-button v-if="confirmations.length" @click="openForm('withdraw')">撤回确认</a-button>
    </div>
    <div v-if="formOpen && !topic.archived_at" class="record-form">
      <p>
        {{ actionLabels[outcomeDraft.action] }} · 本次按议题修订
        {{ outcomeDraft.expectedRevision }} 的条件记录
      </p>
      <a-textarea
        v-model:value="outcomeDraft.explanation"
        aria-label="实际确认说明"
        placeholder="确认说明 / 更正或撤回原因（必填）"
        :maxlength="100000"
      />
      <a-select
        v-model:value="outcomeDraft.referenceKey"
        allow-clear
        aria-label="确认依据工作结果"
        placeholder="工作结果依据（可选）"
        show-search
        option-filter-prop="label"
      >
        <a-select-option
          v-for="item in candidates.filter((item) => item.kind === 'result')"
          :key="candidateKey(item)"
          :value="candidateKey(item)"
          :label="candidateTitle(item)"
          >{{ candidateTitle(item) }}</a-select-option
        >
      </a-select>
      <a-select v-model:value="outcomeDraft.evidenceKind" aria-label="依据类型">
        <a-select-option value="url">网页引用（未读取或验证）</a-select-option>
        <a-select-option value="file">项目文件</a-select-option>
        <a-select-option value="attachment">所选结果所属工作的附件</a-select-option>
      </a-select>
      <a-input
        v-model:value="outcomeDraft.evidenceValue"
        aria-label="实际确认依据"
        placeholder="URL / 项目内相对文件路径 / 附件ID（可选）"
      />
      <p>确认或更正须有工作结果或实际依据；引用仅辅助个人判断。撤回可只填写原因。</p>
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <a-button :disabled="busy || !outcomeDraft.explanation.trim()" @click="save"
        >保存{{ actionLabels[outcomeDraft.action] }}</a-button
      >
      <a-button :disabled="busy" @click="formOpen = false">收起表单（保留草稿）</a-button>
    </div>
    <details
      v-for="(record, index) in confirmations"
      :key="record.id"
      :open="index === 0"
      :id="`topic-confirmation-${record.id}`"
    >
      <summary>
        {{ index === 0 ? '最近记录 · ' : '' }}{{ actionLabels[record.action] }} · 版本
        {{ record.version }} · {{ record.author_name }} · {{ timestamp(record.created_at) }}
      </summary>
      <p>{{ record.explanation }}</p>
      <p>当时议题修订 {{ record.revision_number }}</p>
      <MarkdownPreview
        :content="`预期结果：${record.expected_outcome || '未填写'}\n\n核对条件：${record.verification_conditions || '未填写'}`"
      />
      <router-link v-if="record.reference_snapshot" :to="record.reference_snapshot.href"
        >查看工作结果依据 · 版本 {{ record.reference_snapshot.version }}</router-link
      >
      <details v-if="record.reference_snapshot">
        <summary>引用时结果快照</summary>
        <MarkdownPreview :content="snapshotText(record.reference_snapshot)" />
        <p>
          引用时验收：{{
            record.reference_snapshot.snapshot.status ||
            record.reference_snapshot.snapshot.review_status
          }}
        </p>
      </details>
      <p v-for="(evidence, i) in record.evidence" :key="i">
        <a
          v-if="evidence.kind === 'url'"
          :href="evidence.value"
          target="_blank"
          rel="noopener noreferrer"
          >{{ evidence.value }}</a
        >
        <span v-else>{{ evidence.value }}</span> · {{ evidence.availability_message }}
      </p>
    </details>
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
  confirmationConditionsChanged,
  snapshotText,
  selectedReference,
  stableIntent
} from '@/utils/topicFollowup'
const props = defineProps({
  projectId: String,
  topic: Object,
  candidates: Array,
  confirmations: Array,
  draft: Object
})
const emit = defineEmits(['updated'])
const sharedDraft = reactive(props.draft)
sharedDraft.outcome ||= {
  action: 'confirm',
  explanation: '',
  referenceKey: undefined,
  evidenceKind: 'url',
  evidenceValue: ''
}
const outcomeDraft = sharedDraft.outcome
const formOpen = ref(false),
  error = ref(''),
  busy = ref(false)
const actionLabels = { confirm: '实际达成确认', correct: '更正确认', withdraw: '撤回确认' }
const timestamp = (raw) => (raw ? new Date(raw).toLocaleString('zh-CN') : '')
const conditionsChanged = computed(() =>
  confirmationConditionsChanged(props.topic, props.confirmations[0])
)
let active = true
onBeforeUnmount(() => {
  active = false
})
function openForm(action) {
  outcomeDraft.action = action
  outcomeDraft.expectedRevision = props.topic.revision_number
  outcomeDraft.expectedVersion = props.confirmations[0]?.version || 0
  formOpen.value = true
  error.value = ''
}
async function save() {
  const payload = stableIntent(outcomeDraft, {
    action: outcomeDraft.action,
    explanation: outcomeDraft.explanation,
    expected_revision: outcomeDraft.expectedRevision,
    expected_version: outcomeDraft.expectedVersion,
    reference: selectedReference(outcomeDraft.referenceKey),
    evidence: outcomeDraft.evidenceValue.trim()
      ? [{ kind: outcomeDraft.evidenceKind, value: outcomeDraft.evidenceValue }]
      : []
  })
  busy.value = true
  error.value = ''
  try {
    await api.recordTopicConfirmation(props.projectId, props.topic.id, payload)
    if (!active) return
    formOpen.value = false
    emit('updated')
  } catch (failure) {
    if (active) error.value = describeBoardError(failure)
  } finally {
    if (active) busy.value = false
  }
}
</script>

<style scoped>
.topic-outcome,
.record-form {
  display: grid;
  gap: 10px;
  min-width: 0;
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
a {
  color: var(--main-color);
  overflow-wrap: anywhere;
}
details {
  border-top: 1px solid var(--gray-150);
  padding: 12px 0;
}
</style>
