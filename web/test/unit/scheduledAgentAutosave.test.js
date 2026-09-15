import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createRetriableRequestIds,
  createScheduledAgentAutosave
} from '../../src/components/scheduled-agents/scheduledAgentAutosave.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((complete, fail) => {
    resolve = complete
    reject = fail
  })
  return { promise, reject, resolve }
}

test('首次创建在途的新输入继续保存且不会被旧回包收敛', async () => {
  const createResponse = deferred()
  const requests = []
  const persisted = []
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    createRequestId: () => 'draft-request-1',
    async persist(request) {
      requests.push(structuredClone(request))
      if (!request.jobId) return createResponse.promise
      return { id: request.jobId, ...request.payload }
    },
    onPersisted(job, context) {
      persisted.push({ job, context })
    },
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: { name: 'A', prompt: '旧内容' }, error: '' }, null)
  const flushing = autosave.flush()
  autosave.queue({ payload: { name: 'A', prompt: '最新内容' }, error: '' }, null)
  createResponse.resolve({ id: 'job-1', name: 'A', prompt: '旧内容' })

  assert.equal(await flushing, true)
  assert.deepEqual(
    requests.map(({ jobId, payload, requestId }) => ({ jobId, payload, requestId })),
    [
      {
        jobId: null,
        payload: { name: 'A', prompt: '旧内容' },
        requestId: 'draft-request-1'
      },
      { jobId: 'job-1', payload: { name: 'A', prompt: '最新内容' }, requestId: null }
    ]
  )
  assert.equal(persisted[0].context.finalizeDraft, false)
  assert.equal(persisted[1].context.finalizeDraft, true)
  assert.equal(persisted[1].job.prompt, '最新内容')
})

test('并发 flush 共同等待创建后的最新 PATCH 失败结果', async () => {
  const createResponse = deferred()
  const patchResponse = deferred()
  const requests = []
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    async persist(request) {
      requests.push(structuredClone(request))
      return request.jobId ? patchResponse.promise : createResponse.promise
    },
    onPersisted() {},
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: { name: '任务', prompt: '原始内容' }, error: '' }, null)
  const saving = autosave.flush()
  autosave.queue({ payload: { name: '任务', prompt: '最新内容' }, error: '' }, null)
  const navigation = autosave.flush()
  assert.equal(navigation, saving)

  createResponse.resolve({ id: 'job-1', name: '任务', prompt: '原始内容' })
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(requests.length, 2)
  patchResponse.reject(new Error('PATCH 响应丢失'))

  assert.equal(await saving, false)
  assert.equal(await navigation, false)
})

test('首次创建失败后使用同一 request id 重试', async () => {
  const requests = []
  let attempts = 0
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    createRequestId: () => 'stable-create-request',
    async persist(request) {
      requests.push(structuredClone(request))
      attempts += 1
      if (attempts === 1) throw new Error('响应丢失')
      return { id: 'job-1', ...request.payload }
    },
    onPersisted() {},
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: { name: '任务', prompt: '稳定意图' }, error: '' }, null)

  assert.equal(await autosave.flush(), false)
  assert.equal(await autosave.flush(), true)
  assert.equal(requests[0].requestId, 'stable-create-request')
  assert.deepEqual(requests[0], requests[1])
})

test('创建响应丢失后先原样重放创建意图，再保存后续编辑', async () => {
  const requests = []
  let attempts = 0
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    createRequestId: () => 'stable-create-request',
    async persist(request) {
      requests.push(structuredClone(request))
      attempts += 1
      if (attempts === 1) throw new Error('响应丢失')
      return { id: request.jobId || 'job-1', ...request.payload }
    },
    onPersisted() {},
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: { name: '任务', prompt: '原始意图' }, error: '' }, null)
  assert.equal(await autosave.flush(), false)

  autosave.queue({ payload: { name: '任务', prompt: '后续编辑' }, error: '' }, null)
  assert.equal(await autosave.flush(), true)
  assert.deepEqual(
    requests.map(({ jobId, payload, requestId }) => ({ jobId, payload, requestId })),
    [
      {
        jobId: null,
        payload: { name: '任务', prompt: '原始意图' },
        requestId: 'stable-create-request'
      },
      {
        jobId: null,
        payload: { name: '任务', prompt: '原始意图' },
        requestId: 'stable-create-request'
      },
      { jobId: 'job-1', payload: { name: '任务', prompt: '后续编辑' }, requestId: null }
    ]
  )
})

test('确定失败的创建允许修正配置并使用新 request id', async () => {
  const requests = []
  const createResponse = deferred()
  let requestSequence = 0
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    createRequestId: () => `create-request-${++requestSequence}`,
    async persist(request) {
      requests.push(structuredClone(request))
      if (requests.length === 1) return createResponse.promise
      return { id: 'job-1', ...request.payload }
    },
    onPersisted() {},
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: { name: '任务', project_id: 'deleted' }, error: '' }, null)
  const flushing = autosave.flush()
  autosave.queue({ payload: { name: '任务', project_id: 'valid' }, error: '' }, null)
  const error = new Error('Project 已删除')
  error.status = 404
  createResponse.reject(error)

  assert.equal(await flushing, true)
  assert.deepEqual(
    requests.map(({ payload, requestId }) => ({ payload, requestId })),
    [
      { payload: { name: '任务', project_id: 'deleted' }, requestId: 'create-request-1' },
      { payload: { name: '任务', project_id: 'valid' }, requestId: 'create-request-2' }
    ]
  )
})

test('未知创建结果未收敛时不能丢弃非法草稿', async () => {
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    persist: async () => {
      throw new Error('响应丢失')
    },
    onPersisted() {},
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: { name: '任务', prompt: '可能已创建' }, error: '' }, null)
  assert.equal(await autosave.flush(), false)
  autosave.queue({ payload: null, error: '任务指令不能为空' }, null)

  assert.equal(autosave.canDiscardInvalidDraft(), false)
  assert.equal(await autosave.flush(), false)
})

test('从未发送创建请求的非法草稿可以直接丢弃', () => {
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    persist: async () => ({ id: 'unused' }),
    onPersisted() {},
    onState() {}
  })

  autosave.beginDraft()
  autosave.queue({ payload: null, error: '任务指令不能为空' }, null)

  assert.equal(autosave.canDiscardInvalidDraft(), true)
})

test('立即运行失败时保留 request id，完成后才生成新请求', () => {
  let sequence = 0
  const requests = createRetriableRequestIds(() => `manual-request-${++sequence}`)

  assert.equal(requests.get('job-1'), 'manual-request-1')
  assert.equal(requests.get('job-1'), 'manual-request-1')
  assert.equal(requests.get('job-2'), 'manual-request-2')

  requests.complete('job-1')
  assert.equal(requests.get('job-1'), 'manual-request-3')
})

test('保存失败保留同一 payload 并阻止离开，重试成功后才放行', async () => {
  const requests = []
  const states = []
  let attempts = 0
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    async persist(request) {
      requests.push(structuredClone(request))
      attempts += 1
      if (attempts === 1) throw new Error('网络中断')
      return { id: request.jobId, ...request.payload }
    },
    onPersisted() {},
    onState(next) {
      states.push(next)
    }
  })

  autosave.queue({ payload: { name: '任务', prompt: '不可丢失' }, error: '' }, 'job-1')

  assert.equal(await autosave.flush(), false)
  assert.match(states.at(-1).error, /网络中断/)
  assert.equal(await autosave.flush(), true)
  assert.equal(requests.length, 2)
  assert.deepEqual(requests[0], requests[1])
})

test('保存请求在途时出现非法编辑，旧回包不能覆盖状态或允许离开', async () => {
  const response = deferred()
  const states = []
  const autosave = createScheduledAgentAutosave({
    delay: 60_000,
    persist: () => response.promise,
    onPersisted() {},
    onState(next) {
      states.push(next.state)
    }
  })

  autosave.queue({ payload: { name: '任务', prompt: '合法内容' }, error: '' }, 'job-1')
  const flushing = autosave.flush()
  autosave.queue({ payload: null, error: '任务指令不能为空' }, 'job-1')
  response.resolve({ id: 'job-1', name: '任务', prompt: '合法内容' })

  assert.equal(await flushing, false)
  assert.equal(states.at(-1), 'invalid')
  assert.equal(await autosave.flush(), false)
})
