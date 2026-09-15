import test from 'node:test'
import assert from 'node:assert/strict'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { createAsyncPanel } from '../../src/utils/asyncPanel.js'

test('异步面板成功后透传 props 与事件', async () => {
  const Panel = createAsyncPanel(async () => ({
    props: ['label'],
    setup: (props, { emit }) => {
      emit('ready', props.label)
      return () => h('p', props.label)
    }
  }))
  const events = []
  const html = await renderToString(
    createSSRApp(() => h(Panel, { label: '已加载', onReady: (label) => events.push(label) }))
  )
  assert.match(html, /已加载/)
  assert.deepEqual(events, ['已加载'])
})

test('异步面板下载失败显示错误与恢复入口', async () => {
  const Panel = createAsyncPanel(async () => {
    throw new Error('chunk download failed')
  })
  const app = createSSRApp(() => h(Panel))
  const errors = []
  app.config.errorHandler = (error) => errors.push(error.message)
  const html = await renderToString(app)
  assert.deepEqual(errors, ['chunk download failed'])
  assert.match(html, /role="alert"/)
  assert.match(html, /面板加载失败/)
  assert.match(html, /重新加载页面/)
})
