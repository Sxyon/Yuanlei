import assert from 'node:assert/strict'
import test from 'node:test'

import { useStreamSmoother } from '../../src/composables/useStreamSmoother.js'

/** 用确定性帧时钟回放输入，并核对实际输出正文。 */
function createPlayback(t, frameMs = 1000 / 60) {
  let now = 0
  let sequence = 0
  const frames = new Map()
  t.mock.method(performance, 'now', () => now)
  t.mock.method(globalThis, 'setTimeout', (callback) => {
    frames.set(++sequence, callback)
    return sequence
  })
  t.mock.method(globalThis, 'clearTimeout', (id) => frames.delete(id))
  const states = Object.fromEntries(
    ['a', 'b'].map((id) => [id, { onGoingConv: { msgChunks: {} } }])
  )
  const smoother = useStreamSmoother({ getThreadState: (id) => states[id] })
  t.after(() => smoother.resetThread())
  const chunks = (thread = 'a', id = 'm') => states[thread].onGoingConv.msgChunks[id] || []
  const content = (thread = 'a', id = 'm') =>
    chunks(thread, id)
      .map((c) => c.content || '')
      .join('')
  const samples = []
  return {
    smoother,
    chunks,
    content,
    samples,
    frames,
    push: (text, thread = 'a', id = 'm') =>
      smoother.pushChunk({ id, type: 'AIMessageChunk', content: text }, thread),
    advance(ms) {
      const end = now + ms
      while (now + frameMs <= end + 0.001) {
        now += frameMs
        const callbacks = [...frames.values()]
        frames.clear()
        callbacks.forEach((callback) => callback())
        samples.push({ time: now, text: content() })
      }
    }
  }
}

test('突发大文本先缓冲并渐进追赶，不同步倾倒整批', (t) => {
  const p = createPlayback(t)
  p.push('文'.repeat(200))
  assert.equal(p.content(), '')
  p.advance(150)
  assert.equal(p.content(), '')
  p.advance(150)
  assert.ok(p.content().length > 0 && p.content().length < 100)
  p.advance(1200)
  assert.equal(p.content(), '文'.repeat(200))
  const increments = p.samples.slice(1).map((s, i) => s.text.length - p.samples[i].text.length)
  assert.ok(Math.max(...increments) < 20, '单帧不能倾倒大部分正文')
  assert.equal(p.frames.size, 0)
})

test('每 300 ms 一批正文持续推进，包到达不会立即改变显示', (t) => {
  const p = createPlayback(t)
  for (let i = 0; i < 8; i++) {
    const before = p.content()
    p.push('测'.repeat(24))
    assert.equal(p.content(), before)
    p.advance(300)
  }
  p.advance(1000)
  assert.equal(p.content(), '测'.repeat(192))
  const changes = p.samples.filter((s, i) => i > 0 && s.text !== p.samples[i - 1].text)
  const gaps = changes.slice(1).map((s, i) => s.time - changes[i].time)
  assert.ok(Math.max(...gaps) <= 100, `播放最大停顿 ${Math.max(...gaps)} ms`)
})

test('flush 完整交付正文、推理和工具参数，并取消全部残留帧', (t) => {
  const p = createPlayback(t)
  p.push('文'.repeat(80))
  p.push('本'.repeat(80))
  p.smoother.pushChunk(
    {
      id: 'm',
      content: '',
      reasoning_content: '思考'
    },
    'a'
  )
  p.push('另一条正文', 'a', 'other')
  p.smoother.flushThread('a')
  assert.equal(p.content(), '文'.repeat(80) + '本'.repeat(80))
  assert.equal(p.content('a', 'other'), '另一条正文')
  assert.equal(p.frames.size, 0)
  p.smoother.pushChunk(
    {
      id: 'm',
      content: '',
      tool_call_chunks: [{ index: 0, id: 'tool', name: 'search', args: '{"q":' }]
    },
    'a'
  )
  p.smoother.pushChunk(
    { id: 'm', content: '', tool_call_chunks: [{ index: 0, args: '"查询"}' }] },
    'a'
  )
  p.smoother.flushThread('a')
  assert.equal(p.content(), '文'.repeat(80) + '本'.repeat(80))
  assert.equal(
    p
      .chunks()
      .map((c) => c.reasoning_content || '')
      .join(''),
    '思考'
  )
  assert.equal(
    p
      .chunks()
      .flatMap((c) => c.tool_call_chunks || [])
      .map((c) => c.args)
      .join(''),
    '{"q":"查询"}'
  )
  const count = p.chunks().length
  assert.equal(p.frames.size, 0)
  p.advance(1000)
  assert.equal(p.chunks().length, count)
})

test('工具调用立即透传，之前的同消息文本先完整呈现', (t) => {
  const p = createPlayback(t)
  p.push('开始查询')
  p.smoother.pushChunk(
    {
      id: 'm',
      content: '',
      tool_call_chunks: [{ index: 0, id: 'call', name: 'search', args: '{"q":"问题"}' }]
    },
    'a'
  )
  assert.equal(p.content(), '开始查询')
  assert.deepEqual(p.chunks().at(-1).tool_call_chunks, [
    { index: 0, id: 'call', name: 'search', args: '{"q":"问题"}' }
  ])
  assert.equal(p.frames.size, 0)
})

test('已知完整字素不会在逐帧切片时被拆开', (t) => {
  const p = createPlayback(t)
  const unit = '👨‍👩‍👧‍👦'
  p.push(unit.repeat(5))
  p.advance(1500)
  assert.equal(p.content(), unit.repeat(5))
  for (const sample of p.samples) {
    assert.equal(sample.text.length % unit.length, 0, `残缺字素：${sample.text}`)
  }
})

test('reset 只清理对应线程，重复消息 ID 不串流', (t) => {
  const p = createPlayback(t)
  p.push('丢弃内容', 'a')
  p.push('保留内容', 'b')
  p.smoother.resetThread('a')
  p.advance(1000)
  assert.equal(p.content('a'), '')
  assert.equal(p.content('b'), '保留内容')
  assert.equal(p.frames.size, 0)
})

test('播放进度按经过时间计算，120 Hz 不会比 60 Hz 倍速', (t) => {
  const slow = createPlayback(t)
  slow.push('测'.repeat(300))
  slow.advance(400)
  const slowLength = slow.content().length
  slow.smoother.resetThread()
  t.mock.restoreAll()
  const fast = createPlayback(t, 1000 / 120)
  fast.push('测'.repeat(300))
  fast.advance(400)
  assert.ok(slowLength > 0 && slowLength < 300)
  assert.ok(
    Math.abs(fast.content().length - slowLength) <= 8,
    `60 Hz=${slowLength}, 120 Hz=${fast.content().length}`
  )
})

test('一秒断流时显示完已有文字，恢复后继续且最终内容准确', (t) => {
  const p = createPlayback(t)
  p.push('第一段文字')
  p.advance(1000)
  assert.equal(p.content(), '第一段文字')
  assert.equal(p.frames.size, 0)
  p.push('恢复后的文字')
  p.advance(500)
  assert.equal(p.content(), '第一段文字恢复后的文字')
  assert.equal(p.frames.size, 0)
})

test('用户启用减少动态效果后及时交付已有缓冲与新内容', (t) => {
  const p = createPlayback(t)
  p.push('缓冲文字')
  globalThis.window = { matchMedia: () => ({ matches: true }) }
  t.after(() => {
    delete globalThis.window
  })
  p.push('新文字')
  assert.equal(p.content(), '缓冲文字新文字')
  assert.equal(p.frames.size, 0)
})

test('reset 全部线程后晚到帧不再输出，重新使用同一 ID 可独立播放', (t) => {
  const p = createPlayback(t)
  p.push('旧正文', 'a')
  p.push('旧子线程', 'b')
  const callbacks = [...p.frames.values()]
  p.smoother.resetThread()
  callbacks.forEach((callback) => callback())
  p.advance(1000)
  assert.equal(p.content('a'), '')
  assert.equal(p.content('b'), '')
  assert.equal(p.frames.size, 0)
  p.push('新正文')
  p.advance(500)
  assert.equal(p.content(), '新正文')
})
