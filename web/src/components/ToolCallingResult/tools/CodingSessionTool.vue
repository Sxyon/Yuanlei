<template>
  <BaseToolCall :tool-call="toolCall">
    <template #header>
      <div class="sep-header">
        <span class="note">{{ headerText }}</span>
        <span class="separator" v-if="detail"></span>
        <span class="description" v-if="detail">
          <span class="code">{{ detail }}</span>
        </span>
        <a-button
          v-if="sessionId"
          size="small"
          type="link"
          :loading="loading"
          @click="loadDetail"
        >
          {{ turns.length ? '刷新轮次' : '查看轮次' }}
        </a-button>
        <a-button v-if="sessionId" size="small" type="link" @click="terminalOpen = true">
          打开终端
        </a-button>
      </div>
      <div v-if="turns.length" class="coding-turns">
        <div v-for="turn in turns" :key="turn.seq" class="coding-turn">
          <span class="turn-seq">#{{ turn.seq }}</span>
          <span class="turn-status" :class="turn.status">{{ turn.status }}</span>
          <span class="turn-summary">{{ turn.summary || '（无摘要）' }}</span>
        </div>
      </div>
    </template>
  </BaseToolCall>
  <CodingTerminalModal v-model:open="terminalOpen" :session-id="sessionId" />
</template>

<script setup>
import { computed, onUnmounted, ref } from 'vue'
import BaseToolCall from '../BaseToolCall.vue'
import { parseToolCallArgs } from '../toolRegistry'
import { codingSessionApi } from '@/apis/coding_session_api'
import CodingTerminalModal from '@/components/CodingTerminalModal.vue'

const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled'])

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

const sessionId = computed(() => {
  const fromArgs = parsedArgs.value.session_id
  const raw = props.toolCall.tool_call_result?.content ?? props.toolCall.result
  let parsed = null
  if (typeof raw === 'string' && raw.trim().startsWith('{')) {
    try {
      parsed = JSON.parse(raw)
    } catch {
      parsed = null
    }
  } else if (raw && typeof raw === 'object') {
    parsed = raw
  }
  return fromArgs || parsed?.session_id || ''
})

const turns = ref([])
const loading = ref(false)
const terminalOpen = ref(false)
const running = ref(false)
let pollTimer = null

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const fetchDetail = async ({ silent = false } = {}) => {
  if (!sessionId.value) {
    return
  }
  if (!silent) {
    loading.value = true
  }
  try {
    const response = await codingSessionApi.detail(sessionId.value)
    turns.value = Array.isArray(response?.turns) ? response.turns : []
    running.value = !TERMINAL_STATUSES.has(response?.status)
    if (running.value) {
      if (!pollTimer) {
        pollTimer = setInterval(() => fetchDetail({ silent: true }), 2000)
      }
    } else {
      stopPolling()
    }
  } catch {
    turns.value = []
    stopPolling()
  } finally {
    loading.value = false
  }
}

const loadDetail = () => fetchDetail()

onUnmounted(stopPolling)
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

.coding-turns {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 6px;
  width: 100%;
}

.coding-turn {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary, #646a73);
}

.turn-seq {
  font-weight: 600;
}

.turn-status.completed {
  color: var(--color-success, #34c759);
}

.turn-status.failed {
  color: var(--color-error, #ff4d4f);
}

.turn-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
