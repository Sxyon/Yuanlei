<template>
  <details class="project-filters">
    <summary>筛选项目<span v-if="active"> · 已筛选</span></summary>
    <div class="filter-fields">
      <label>类型
        <select :value="modelValue.type || ''" @change="update('type', $event.target.value)">
          <option value="">全部类型</option>
          <option v-for="item in projectTypes" :key="item.value" :value="item.value">{{ item.label }}</option>
        </select>
      </label>
      <label>分类
        <select :value="modelValue.category || ''" @change="update('category', $event.target.value)">
          <option value="">全部分类</option>
          <option v-for="category in categories" :key="category" :value="category">{{ category }}</option>
        </select>
      </label>
      <label>标签
        <select :value="modelValue.tag || ''" @change="update('tag', $event.target.value)">
          <option value="">全部标签</option>
          <option v-for="tag in tags" :key="tag" :value="tag">{{ tag }}</option>
        </select>
      </label>
      <button v-if="active" type="button" @click="emit('update:modelValue', {})">清除筛选</button>
    </div>
  </details>
</template>

<script setup>
import { computed } from 'vue'
import { projectTypes } from '@/utils/projectSelection'

const props = defineProps({
  projects: { type: Array, default: () => [] },
  modelValue: { type: Object, default: () => ({}) }
})
const emit = defineEmits(['update:modelValue'])
const active = computed(() => Object.values(props.modelValue).some(Boolean))
const categories = computed(() => [...new Set(props.projects.map(p => p.category).filter(Boolean))].sort())
const tags = computed(() => [...new Set(props.projects.flatMap(p => p.tags || []))].sort())
/** 各条件组合匹配，只更新筛选，不产生项目选择事件。 */
function update(key, value) {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}
</script>

<style scoped lang="less">
.project-filters { margin: 8px; color: var(--gray-600); font-size: 12px; }
summary { cursor: pointer; padding: 4px 0; }
.filter-fields { display: grid; gap: 6px; padding: 6px 0; }
label { display: grid; grid-template-columns: 30px minmax(0, 1fr); align-items: center; gap: 6px; }
select { width: 100%; min-width: 0; padding: 4px; border: 1px solid var(--gray-150); border-radius: 4px; background: var(--gray-0); color: var(--gray-900); }
button { border: 0; background: transparent; color: var(--main-color); cursor: pointer; text-align: left; padding: 4px 0; }
summary:focus-visible, select:focus-visible, button:focus-visible { outline: 2px solid var(--main-color); outline-offset: 2px; }
</style>
