import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildCredentialPayload,
  credentialAvailabilityOf,
  credentialModeOf,
  credentialSourceLabel,
  findModelProvider,
  modelOptionsOf,
  providerOptionsOf,
  validateCredentialDraft
} from '../../src/utils/codingCredentialForm.js'

test('credentialModeOf 按 source/key_mode 判定三种模式', () => {
  assert.equal(credentialModeOf({ source: 'manual' }), 'manual')
  assert.equal(credentialModeOf({ source: 'model_provider', key_mode: 'inherit' }), 'inherit')
  assert.equal(credentialModeOf({ source: 'model_provider', key_mode: 'custom' }), 'custom')
  assert.equal(credentialModeOf(null), 'manual')
})

test('validateCredentialDraft 按模式校验必填字段', () => {
  assert.equal(
    validateCredentialDraft({ executor: 'opencode', mode: 'manual', provider: 'sf', api_key: 'sk' }),
    ''
  )
  assert.match(
    validateCredentialDraft({ executor: 'opencode', mode: 'manual', provider: '', api_key: 'sk' }),
    /供应商标识/
  )
  assert.equal(
    validateCredentialDraft({
      executor: 'codex',
      mode: 'inherit',
      model_provider_id: 'sf',
      model: 'm1'
    }),
    ''
  )
  assert.match(
    validateCredentialDraft({
      executor: 'codex',
      mode: 'inherit',
      model_provider_id: 'sf',
      model: ''
    }),
    /请选择模型/
  )
  assert.match(
    validateCredentialDraft({
      executor: 'codex',
      mode: 'custom',
      model_provider_id: 'sf',
      model: 'm1',
      api_key: ''
    }),
    /单独密钥/
  )
})

test('buildCredentialPayload 只提交当前模式需要的字段', () => {
  assert.deepEqual(
    buildCredentialPayload({
      executor: 'opencode',
      mode: 'manual',
      provider: ' sf ',
      base_url: '',
      model: '',
      api_key: 'sk'
    }),
    {
      executor: 'opencode',
      source: 'manual',
      provider: 'sf',
      api_key: 'sk',
      base_url: null,
      model: null
    }
  )
  assert.deepEqual(
    buildCredentialPayload({
      executor: 'codex',
      mode: 'inherit',
      model_provider_id: 'siliconflow-cn',
      model: 'm1',
      api_key: 'sk-ignored'
    }),
    {
      executor: 'codex',
      source: 'model_provider',
      model_provider_id: 'siliconflow-cn',
      key_mode: 'inherit',
      model: 'm1'
    }
  )
  assert.deepEqual(
    buildCredentialPayload({
      executor: 'codex',
      mode: 'custom',
      model_provider_id: 'siliconflow-cn',
      model: 'm1',
      api_key: 'sk-own'
    }),
    {
      executor: 'codex',
      source: 'model_provider',
      model_provider_id: 'siliconflow-cn',
      key_mode: 'custom',
      model: 'm1',
      api_key: 'sk-own'
    }
  )
})

test('credentialAvailabilityOf 与 credentialSourceLabel 生成展示文案', () => {
  assert.deepEqual(credentialAvailabilityOf({ source: 'manual' }), {
    available: true,
    label: '可用',
    detail: ''
  })
  assert.deepEqual(
    credentialAvailabilityOf({
      source: 'model_provider',
      availability: 'unavailable',
      unavailable_reason: 'provider_disabled',
      unavailable_detail: '引用的模型供应商已停用'
    }),
    { available: false, label: '供应商已停用', detail: '引用的模型供应商已停用' }
  )
  assert.equal(credentialSourceLabel({ source: 'manual', provider: 'sf' }), 'sf')
  assert.equal(
    credentialSourceLabel({
      source: 'model_provider',
      provider_display_name: 'SiliconFlow',
      model: 'm1'
    }),
    'SiliconFlow · m1'
  )
})

test('供应商与模型选项映射保留停用标记', () => {
  const providers = [
    { provider_id: 'a', display_name: 'A', is_enabled: true, models: [{ id: 'm1', display_name: 'M1' }] },
    { provider_id: 'b', display_name: 'B', is_enabled: false, models: [] }
  ]
  assert.deepEqual(providerOptionsOf(providers), [
    { value: 'a', label: 'A' },
    { value: 'b', label: 'B（已停用）' }
  ])
  assert.deepEqual(modelOptionsOf(findModelProvider(providers, 'a')), [{ value: 'm1', label: 'M1' }])
  assert.equal(findModelProvider(providers, 'missing'), null)
})
