<template>
  <ActionDropdown :upward="upward" v-model:open="open">
    <template #trigger>
      <ActionTrigger
        :label="currentOption.label"
        :open="open"
        :class="{ 'is-trusted': modelValue === 'always_trust' }"
        collapse-label
      >
        <template #icon><component :is="currentOption.icon" :size="16" /></template>
      </ActionTrigger>
    </template>
    <div role="menu" aria-label="工具审批模式">
      <button
        v-for="option in options"
        :key="option.value"
        type="button"
        role="menuitemradio"
        :aria-checked="modelValue === option.value"
        class="config-dropdown-item"
        :class="{ selected: modelValue === option.value }"
        @click="selectMode(option.value)"
      >
        <component
          :is="option.icon"
          :size="15"
          class="config-dropdown-item-icon"
          :class="{ trusted: option.value === 'always_trust' }"
        />
        <span class="config-dropdown-item-label">{{ option.label }}</span>
        <Check v-if="modelValue === option.value" :size="14" class="config-dropdown-item-check" />
      </button>
    </div>
  </ActionDropdown>
</template>

<script setup>
import { computed, ref } from 'vue'
import { Check, Hand, ShieldAlert } from '@lucide/vue'
import ActionDropdown from '@/components/common/ActionDropdown.vue'
import ActionTrigger from '@/components/common/ActionTrigger.vue'

const props = defineProps({
  upward: { type: Boolean, default: false },
  modelValue: { type: String, default: 'default' }
})

const emit = defineEmits(['update:modelValue'])
const options = [
  {
    value: 'default',
    label: '请求审批',
    icon: Hand
  },
  {
    value: 'always_trust',
    label: '完全信任',
    icon: ShieldAlert
  }
]

const open = ref(false)
const currentOption = computed(
  () => options.find((option) => option.value === props.modelValue) || options[0]
)

const selectMode = (mode) => {
  emit('update:modelValue', mode)
  open.value = false
}
</script>

<style scoped lang="less">
.is-trusted {
  color: var(--color-warning-700);
}
</style>

<style lang="less">
.config-dropdown-overlay .config-dropdown-item-icon.trusted {
  color: var(--color-warning-700);
}
</style>
