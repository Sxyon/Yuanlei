<script setup>
import { LoaderCircle, AlertCircle } from '@lucide/vue'
defineProps({ block: { type: Object, required: true }, result: { type: Object, required: true } })
defineEmits(['navigate', 'retry'])
const states = { empty: '暂无记录', unbound: '尚未选择或绑定', missing: '对象或资料缺失', denied: '无权读取', error: '读取失败' }
</script>
<template>
  <section class="theme-block" :data-block="block.id" :data-state="result.state">
    <header><h2>{{ block.title }}</h2><button v-if="block.action" class="theme-link" @click="$emit('navigate', block.action)">查看 →</button></header>
    <template v-if="result.state === 'ready' || result.previous || result.state === 'empty' && ['records', 'discussion'].includes(block.type)"><p v-if="result.previous" class="theme-meta" role="status">正在刷新当前列表，当前内容为上次读取。</p><slot /></template>
    <div v-else-if="result.state === 'loading'" class="theme-state" role="status"><LoaderCircle :size="18" class="theme-loading" />正在读取…</div>
    <div v-else class="theme-state" :class="{ error: ['error', 'denied'].includes(result.state) }" :role="['error', 'denied'].includes(result.state) ? 'alert' : 'status'">
      <h3><AlertCircle v-if="['error', 'denied'].includes(result.state)" :size="16" />{{ states[result.state] || '响应不受支持' }}</h3>
      <p>{{ result.message || (result.state === 'empty' ? '当前范围没有业务记录，讨论不会自动成为正式任务。' : '当前内容不可用。') }}</p>
      <button v-if="['error', 'missing'].includes(result.state)" @click="$emit('retry')">重新读取</button>
    </div>
  </section>
</template>
