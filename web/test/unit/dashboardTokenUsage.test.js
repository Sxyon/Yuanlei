import test from 'node:test'
import assert from 'node:assert/strict'
import { formatTokenUsage } from '../../src/utils/dashboard.js'

test('Token 用量区分零、缺失与部分统计', () => {
  assert.equal(formatTokenUsage({ total_tokens: null, token_usage_complete: false }), '未记录')
  assert.equal(formatTokenUsage({ total_tokens: 0, token_usage_complete: true }), '0')
  assert.equal(formatTokenUsage({ total_tokens: 200, token_usage_complete: true }), '200')
  assert.equal(formatTokenUsage({ total_tokens: 120, token_usage_complete: false }), '≥ 120')
})
