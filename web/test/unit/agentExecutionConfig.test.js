import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildExecutionConfigPatch,
  cloneExecutionConfig,
  normalizeCodingSettings,
  normalizeSandboxPolicy,
  parseExecutionConfig
} from '../../src/utils/agentExecutionConfig.js'

test('parseExecutionConfig 在无配置时给出共享临时沙盒与空执行器', () => {
  assert.deepEqual(parseExecutionConfig(null), {
    sandbox: { mode: 'shared', lifecycle: 'ephemeral', resume_policy: 'auto', idle_suspend_seconds: null },
    coding: { executors: [], default_executor: null }
  })
})

test('normalizeSandboxPolicy 共享模式固定 ephemeral，非法值回落默认', () => {
  assert.deepEqual(
    normalizeSandboxPolicy({ mode: 'shared', lifecycle: 'resident', resume_policy: 'confirm' }),
    {
      mode: 'shared',
      lifecycle: 'ephemeral',
      resume_policy: 'confirm',
      idle_suspend_seconds: null
    }
  )
  assert.deepEqual(
    normalizeSandboxPolicy({ mode: 'dedicated', lifecycle: 'bogus', idle_suspend_seconds: -5 }),
    {
      mode: 'dedicated',
      lifecycle: 'ephemeral',
      resume_policy: 'auto',
      idle_suspend_seconds: 0
    }
  )
})

test('normalizeCodingSettings 过滤未知执行器并丢弃失效默认值', () => {
  assert.deepEqual(
    normalizeCodingSettings({ executors: ['codex', 'unknown', 'opencode'], default_executor: 'unknown' }),
    { executors: ['opencode', 'codex'], default_executor: null }
  )
  assert.deepEqual(normalizeCodingSettings({ executors: ['opencode', 'codex'], default_executor: 'codex' }), {
    executors: ['opencode', 'codex'],
    default_executor: 'codex'
  })
})

test('buildExecutionConfigPatch 只提交发生变化的段', () => {
  const initial = parseExecutionConfig({
    sandbox: { mode: 'shared' },
    coding: { executors: ['opencode'], default_executor: 'opencode' }
  })

  assert.deepEqual(buildExecutionConfigPatch({ initial, current: initial }), {})

  const sandboxOnly = buildExecutionConfigPatch({
    initial,
    current: {
      sandbox: { mode: 'dedicated', lifecycle: 'persistent', resume_policy: 'auto', idle_suspend_seconds: 600 },
      coding: cloneExecutionConfig(initial).coding
    }
  })
  assert.deepEqual(sandboxOnly, {
    sandbox: {
      mode: 'dedicated',
      lifecycle: 'persistent',
      resume_policy: 'auto',
      idle_suspend_seconds: 600
    }
  })

  const codingOnly = buildExecutionConfigPatch({
    initial,
    current: {
      sandbox: normalizeSandboxPolicy(initial.sandbox),
      coding: { executors: ['opencode', 'codex'], default_executor: 'codex' }
    }
  })
  assert.deepEqual(codingOnly, {
    coding: { executors: ['opencode', 'codex'], default_executor: 'codex' }
  })
})

test('cloneExecutionConfig 返回与源对象无关的副本', () => {
  const source = parseExecutionConfig({
    sandbox: { mode: 'dedicated', lifecycle: 'resident' },
    coding: { executors: ['codex'], default_executor: 'codex' }
  })
  const clone = cloneExecutionConfig(source)
  clone.sandbox.lifecycle = 'ephemeral'
  clone.coding.executors.push('opencode')

  assert.equal(source.sandbox.lifecycle, 'resident')
  assert.deepEqual(source.coding.executors, ['codex'])
})
