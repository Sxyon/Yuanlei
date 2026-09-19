<template>
  <a-modal
    :open="open"
    title="编码会话终端"
    width="900px"
    :footer="null"
    destroy-on-close
    @cancel="close"
  >
    <div class="terminal-toolbar">
      <span class="terminal-hint">
        终端接管期间请避免同时驱动同一会话；关闭窗口即交还 agent。
      </span>
      <a-button size="small" :loading="connecting" @click="connect">重新连接</a-button>
    </div>
    <div ref="terminalHost" class="terminal-host"></div>
  </a-modal>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { codingSessionApi } from '@/apis/coding_session_api'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  sessionId: {
    type: String,
    default: ''
  }
})

const emit = defineEmits(['update:open'])

const terminalHost = ref(null)
const connecting = ref(false)
let term = null
let fitAddon = null
let socket = null

const wsUrl = (path) => {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

const send = (type, data) => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type, data }))
  }
}

const disposeTerminal = () => {
  if (socket) {
    socket.onmessage = null
    socket.onclose = null
    socket.close()
    socket = null
  }
  if (term) {
    term.dispose()
    term = null
  }
  fitAddon = null
}

const connect = async () => {
  if (!props.sessionId) {
    return
  }
  disposeTerminal()
  connecting.value = true
  try {
    await nextTick()
    import('@xterm/xterm/css/xterm.css').catch(() => {})
    const [xtermModule, fitModule] = await Promise.all([
      import('@xterm/xterm'),
      import('@xterm/addon-fit')
    ])
    const TerminalCtor = xtermModule.Terminal || xtermModule.default?.Terminal
    const FitAddonCtor = fitModule.FitAddon || fitModule.default?.FitAddon
    if (!TerminalCtor || !FitAddonCtor) {
      throw new Error('终端组件不可用')
    }
    term = new TerminalCtor({
      convertEol: true,
      fontSize: 13,
      scrollback: 2000,
      theme: { background: '#1f1f1f' }
    })
    fitAddon = new FitAddonCtor()
    term.loadAddon(fitAddon)
    term.open(terminalHost.value)
    fitAddon.fit()
    term.onData((data) => send('input', data))
    term.onResize(({ cols, rows }) => send('resize', { cols, rows }))

    const ticket = await codingSessionApi.terminalTicket(props.sessionId)
    socket = new WebSocket(wsUrl(ticket.ws_path))
    socket.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data)
        if (payload.type === 'output' || payload.type === 'restore_output') {
          term.write(payload.data || '')
        } else if (payload.type === 'error') {
          term.write(`\r\n[${payload.data || 'terminal error'}]\r\n`)
        }
      } catch {
        term.write(String(event.data))
      }
    }
    socket.onclose = () => {
      term?.write('\r\n[terminal disconnected]\r\n')
    }
  } catch (error) {
    message.error(error?.message || '终端连接失败')
  } finally {
    connecting.value = false
  }
}

const close = () => {
  disposeTerminal()
  emit('update:open', false)
}

watch(
  () => props.open,
  (value) => {
    if (value) {
      connect()
    } else {
      disposeTerminal()
    }
  }
)

onBeforeUnmount(disposeTerminal)
</script>

<style lang="less" scoped>
.terminal-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.terminal-hint {
  color: var(--text-secondary, #646a73);
  font-size: 12px;
}

.terminal-host {
  height: 460px;
  padding: 4px;
  border-radius: 6px;
  background: #1f1f1f;
}
</style>
