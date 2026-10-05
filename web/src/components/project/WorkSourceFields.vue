<template>
  <div class="work-source-fields">
    <label
      >来源议题（可选）
      <a-select
        :value="topicId"
        allow-clear
        :disabled="disabled"
        placeholder="无议题也可创建工作"
        @update:value="$emit('update:topicId', $event)"
      >
        <a-select-option v-for="topic in topics" :key="topic.id" :value="topic.id">{{
          topic.title
        }}</a-select-option>
      </a-select>
    </label>
    <label
      >主要来源决策（可选）
      <a-select
        :value="decisionId"
        allow-clear
        :disabled="disabled"
        placeholder="独立工作可不选决策"
        @update:value="chooseDecision"
      >
        <a-select-option
          v-for="decision in decisions"
          :key="decision.id"
          :value="decision.id"
          :disabled="decision.status !== 'approved'"
        >
          {{ decision.title }} · {{ governanceStatusLabel(decision.status)
          }}{{ decision.requires_review ? ' · 需复核' : '' }}
        </a-select-option>
      </a-select>
    </label>
    <p v-if="mismatch" role="alert">议题须与所选决策的来源议题一致；项目级决策只关联决策。</p>
    <a-alert
      v-if="selected?.requires_review"
      type="warning"
      show-icon
      message="补充决策原依据已变化，需复核"
      description="此补充仍已批准，但不自动成为新的整体方案。请核对后选择；关联不会暂停工作。"
    />
    <a-checkbox
      v-if="selected?.requires_review"
      :checked="reviewConfirmed"
      :disabled="disabled"
      @update:checked="$emit('update:reviewConfirmed', $event)"
      >我已复核此补充，确认作为本工作来源</a-checkbox
    >
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { governanceStatusLabel } from '@/utils/governanceBoard'
const props = defineProps({
  topics: { type: Array, default: () => [] },
  decisions: { type: Array, default: () => [] },
  topicId: String,
  decisionId: String,
  reviewConfirmed: Boolean,
  disabled: Boolean
})
const emit = defineEmits(['update:topicId', 'update:decisionId', 'update:reviewConfirmed'])
const selected = computed(() => props.decisions.find((item) => item.id === props.decisionId))
const mismatch = computed(
  () => props.topicId && selected.value && selected.value.topic_id !== props.topicId
)
function chooseDecision(id) {
  emit('update:decisionId', id)
  emit('update:reviewConfirmed', false)
}
</script>

<style scoped lang="less">
.work-source-fields,
label {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.work-source-fields {
  gap: 12px;
}
p {
  margin: 0;
  color: var(--color-error-700);
}
</style>
