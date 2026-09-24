<template>
  <a-popover
    v-if="visible"
    placement="bottomRight"
    trigger="click"
    @open-change="handleOpenChange"
  >
    <template #content>
      <div class="sandbox-popover">
        <div class="sandbox-title">专属沙盒</div>
        <div class="sandbox-row">
          <span class="sandbox-label">作用域</span>
          <span class="sandbox-value mono">{{ scopeShort }}</span>
        </div>
        <div class="sandbox-row">
          <span class="sandbox-label">状态</span>
          <span class="sandbox-value">{{ statusText }}</span>
        </div>
        <div class="sandbox-row">
          <span class="sandbox-label">生命周期</span>
          <span class="sandbox-value">{{ info?.sandbox?.lifecycle || '—' }}</span>
        </div>
        <div class="sandbox-row">
          <span class="sandbox-label">最后活动</span>
          <span class="sandbox-value">{{ lastActivityText }}</span>
        </div>
        <a-button
          type="primary"
          size="small"
          block
          :loading="opening"
          @click="openTerminal"
        >
          打开沙盒终端
        </a-button>
        <p class="sandbox-hint">
          终端即沙盒内的真实 shell，可直接查看/操作 opencode 会话与 Workdir；未运行时打开会自动预热。
        </p>
      </div>
    </template>
    <button
      type="button"
      class="agent-nav-btn sandbox-chip"
      :class="{ 'is-open': terminalOpen }"
      title="查看该会话的专属沙盒"
    >
      <Box :size="16" class="nav-btn-icon" />
      <span class="hide-text">沙盒</span>
      <span class="sandbox-dot" :class="statusClass" />
    </button>
  </a-popover>
  <CodingTerminalModal v-model:open="terminalOpen" :session-id="terminalSessionId" />
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { Box } from '@lucide/vue'

import { codingThreadApi } from '@/apis/coding_thread_api'
import CodingTerminalModal from '@/components/CodingTerminalModal.vue'

const props = defineProps({
  threadId: { type: String, default: '' }
})

const POLL_INTERVAL_MS = 5000

const info = ref(null)
const opening = ref(false)
const terminalOpen = ref(false)
const terminalSessionId = ref(null)
let pollTimer = null

const visible = computed(() => Boolean(info.value?.enabled))
const scopeShort = computed(() => {
  const key = info.value?.scope_key || ''
  const parts = key.split(':')
  return parts.length >= 4 ? `${parts[1]}/${parts[2].slice(0, 18)}` : key
})
const statusText = computed(() => {
  const sandbox = info.value?.sandbox
  if (!sandbox) return '未创建（首次使用或打开终端时预热）'
  if (sandbox.status === 'active') return '运行中'
  if (sandbox.status === 'suspended') return '已回收（下次使用自动恢复）'
  if (sandbox.status === 'error') return '异常'
  return sandbox.status
})
const statusClass = computed(() => {
  const status = info.value?.sandbox?.status
  if (status === 'active') return 'is-active'
  if (status === 'error') return 'is-error'
  return 'is-idle'
})
const lastActivityText = computed(() => {
  const value = info.value?.sandbox?.last_activity_at
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 19)
})

const load = async () => {
  if (!props.threadId) {
    info.value = null
    return
  }
  try {
    info.value = await codingThreadApi.sandbox(props.threadId)
  } catch {
    info.value = null
  }
}

const handleOpenChange = (open) => {
  if (open) load()
}

const openTerminal = async () => {
  if (!props.threadId) return
  opening.value = true
  try {
    const session = await codingThreadApi.terminal(props.threadId)
    terminalSessionId.value = session.session_id
    terminalOpen.value = true
    await load()
  } catch (error) {
    message.error(error?.message || '沙盒终端不可用')
  } finally {
    opening.value = false
  }
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(load, POLL_INTERVAL_MS)
}

watch(
  () => props.threadId,
  async () => {
    terminalOpen.value = false
    terminalSessionId.value = null
    await load()
  }
)

onMounted(async () => {
  await load()
  startPolling()
})

onBeforeUnmount(stopPolling)
</script>

<style scoped>
.sandbox-chip {
  position: relative;
}

.sandbox-chip.is-open {
  border-color: var(--main-300);
  background: var(--main-50);
}

.sandbox-dot {
  width: 7px;
  height: 7px;
  margin-left: 4px;
  border-radius: 50%;
  background: var(--gray-400);
}

.sandbox-dot.is-active {
  background: var(--color-success-600, #16a34a);
}

.sandbox-dot.is-error {
  background: var(--color-error-600, #dc2626);
}

.sandbox-popover {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 320px;
}

.sandbox-title {
  color: var(--gray-900);
  font-size: 13px;
  font-weight: 600;
}

.sandbox-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
}

.sandbox-label {
  color: var(--gray-500);
  flex-shrink: 0;
}

.sandbox-value {
  color: var(--gray-900);
  text-align: right;
  word-break: break-all;
}

.sandbox-value.mono {
  font-family: var(--font-mono, monospace);
}

.sandbox-hint {
  margin: 0;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.5;
}
</style>
