<template>
  <ModelSelectorComponent
    :model_spec="value"
    model-type="rerank"
    :placeholder="placeholder"
    :size="size === 'default' ? 'small' : size"
    :disabled="disabled"
    @select-model="handleSelect"
  />
</template>

<script setup>
import ModelSelectorComponent from '@/components/ModelSelectorComponent.vue'

defineProps({
  value: { type: String, default: '' },
  placeholder: { type: String, default: '请选择重排序模型' },
  size: { type: String, default: 'small' },
  disabled: { type: Boolean, default: false }
})
const emit = defineEmits(['update:value', 'change'])

/** 保留表单的双向绑定和 change 事件契约。 */
function handleSelect(value) {
  emit('update:value', value)
  emit('change', value)
}
</script>
