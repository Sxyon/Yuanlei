<template>
  <BaseToolCall :tool-call="toolCall">
    <template #header>
      <div class="sep-header">
        <span class="note">{{ headerText }}</span>
        <span class="separator" v-if="detail"></span>
        <span class="description" v-if="detail">
          <span class="code">{{ detail }}</span>
        </span>
      </div>
    </template>
  </BaseToolCall>
</template>

<script setup>
import { computed } from 'vue'
import BaseToolCall from '../BaseToolCall.vue'
import { parseToolCallArgs } from '../toolRegistry'

const props = defineProps({
  toolCall: {
    type: Object,
    required: true
  }
})

const parsedArgs = computed(() => parseToolCallArgs(props.toolCall))

const toolName = computed(() => {
  const call = props.toolCall || {}
  return call.name || call.function?.name || ''
})

const headerText = computed(() => {
  const executor = parsedArgs.value.executor || 'opencode'
  const labels = {
    coding_session_start: `启动编码会话（${executor} · 计划轮）`,
    coding_session_send: '编码会话下一轮',
    coding_session_status: '编码会话状态',
    coding_session_await: '等待编码会话',
    coding_session_control: `控制编码会话（${parsedArgs.value.action || 'cancel'}）`,
    coding_session_list: '编码会话列表'
  }
  return labels[toolName.value] || '编码会话'
})

const detail = computed(() => {
  const args = parsedArgs.value
  return args.task || args.message || args.session_id || ''
})
</script>

<style lang="less" scoped>
.sep-header {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.description {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
