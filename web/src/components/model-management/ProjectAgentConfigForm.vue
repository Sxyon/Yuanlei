<template>
  <div class="project-agent-config-form">
    <a-alert
      v-if="!fieldEntries.length"
      type="info"
      message="该智能体后端没有可配置项"
      show-icon
      class="config-alert"
    />
    <a-form v-else layout="vertical" class="config-form">
      <a-form-item v-for="[key, item] in fieldEntries" :key="key" :label="item.name || key">
        <p v-if="item.description" class="config-description">{{ item.description }}</p>

        <ModelSelectorComponent
          v-if="item.kind === 'llm'"
          :model_spec="String(values[key] || '')"
          clearable
          @select-model="(spec) => updateValue(key, spec || '')"
        />

        <a-textarea
          v-else-if="item.kind === 'prompt'"
          :value="values[key] || ''"
          :placeholder="placeholderOf(key)"
          :auto-size="{ minRows: 3, maxRows: 10 }"
          @update:value="(value) => updateValue(key, value)"
        />

        <a-switch
          v-else-if="item.type === 'bool' || item.type === 'boolean'"
          :checked="!!values[key]"
          @update:checked="(checked) => updateValue(key, checked)"
        />

        <a-select
          v-else-if="isSingleSelect(item)"
          :value="values[key] ?? undefined"
          :options="optionsOf(item)"
          allow-clear
          class="config-select"
          @update:value="(value) => updateValue(key, value)"
        />

        <a-select
          v-else-if="isListKind(item)"
          mode="multiple"
          :value="Array.isArray(values[key]) ? values[key] : []"
          :options="optionsOf(item)"
          :placeholder="placeholderOf(key)"
          allow-clear
          @update:value="(value) => updateValue(key, value)"
        />

        <a-input-number
          v-else-if="isNumber(item)"
          :value="values[key] ?? null"
          class="config-number"
          @update:value="(value) => updateValue(key, value)"
        />

        <a-input
          v-else
          :value="values[key] ?? ''"
          :placeholder="placeholderOf(key)"
          @update:value="(value) => updateValue(key, value)"
        />

        <a-button
          v-if="overriddenKeys.includes(key)"
          type="link"
          size="small"
          class="reset-field-btn"
          @click="emit('reset-field', key)"
        >
          恢复基础配置
        </a-button>
      </a-form-item>
    </a-form>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'
import {
  getAgentConfigOptionLabel,
  getAgentConfigOptionValue,
  isSingleSelectAgentConfig
} from '@/utils/agentConfigUtils'

const props = defineProps({
  /** 当前项目覆盖层配置值（仅覆盖字段）。 */
  values: { type: Object, default: () => ({}) },
  /** 后端返回的 configurable_items（存储扁平化后的 UI 配置）。 */
  configurableItems: { type: Object, default: () => ({}) },
  /** 智能体基础配置；用于未覆盖字段的占位提示。 */
  baseValues: { type: Object, default: () => ({}) },
  /** 已被项目覆盖的字段；用于展示"恢复基础配置"。 */
  overriddenKeys: { type: Array, default: () => [] },
  /** 可选分组：model / tools / other；为空时展示全部字段。 */
  segment: { type: String, default: '' }
})

const emit = defineEmits(['update:values', 'reset-field'])

const LIST_KINDS = ['tools', 'knowledges', 'mcps', 'skills', 'subagents', 'preload_skills']

const allFieldEntries = computed(() =>
  Object.entries(props.configurableItems || {}).map(([key, raw]) => {
    const item = raw?.x_oap_ui_config ? { ...raw, ...raw.x_oap_ui_config } : raw || {}
    return [key, item]
  })
)

const isResourceKind = (kind) => LIST_KINDS.includes(kind)

const fieldEntries = computed(() => {
  if (!props.segment) return allFieldEntries.value
  return allFieldEntries.value.filter(([, item]) => {
    const kind = item?.kind
    if (props.segment === 'model') return kind === 'llm' || kind === 'prompt'
    if (props.segment === 'tools') return isResourceKind(kind)
    if (props.segment === 'other') return kind !== 'llm' && kind !== 'prompt' && !isResourceKind(kind)
    return true
  })
})

const isListKind = (item) => LIST_KINDS.includes(item?.kind)
const isNumber = (item) => ['number', 'int', 'integer', 'float'].includes(item?.type)
const isSingleSelect = (item) => isSingleSelectAgentConfig(item) && !isListKind(item)

const optionsOf = (item) =>
  (item?.options || []).map((option) => ({
    value: getAgentConfigOptionValue(option),
    label: getAgentConfigOptionLabel(option)
  }))

const placeholderOf = (key) =>
  key in (props.baseValues || {}) ? '未覆盖：继承基础配置' : '未设置'

const updateValue = (key, value) => {
  emit('update:values', {
    ...props.values,
    [key]: value === undefined ? null : value
  })
}
</script>

<style scoped>
.project-agent-config-form {
  display: flex;
  flex-direction: column;
}

.config-description {
  margin: 0 0 6px;
  color: var(--text-color-secondary, #8c8c8c);
  font-size: 12px;
  line-height: 1.5;
}

.config-select,
.config-number {
  width: 100%;
}

.reset-field-btn {
  padding: 0;
  height: auto;
  font-size: 12px;
}

.config-alert {
  margin-bottom: 12px;
}
</style>
