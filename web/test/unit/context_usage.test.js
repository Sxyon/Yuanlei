import assert from 'node:assert/strict'
import test from 'node:test'

import {
  calculateContextRatio,
  formatContextToken,
  formatContextUsageTooltip,
  getContextUsageTone,
  resolveContextPressureTokens,
  shouldSuggestContextCompression
} from '../../src/utils/contextUsage.js'

test('formatContextToken: 正确格式化 K / M 及普通数值', () => {
  assert.equal(formatContextToken(0), '0')
  assert.equal(formatContextToken(-10), '0')
  assert.equal(formatContextToken(null), '0')
  assert.equal(formatContextToken(undefined), '0')
  assert.equal(formatContextToken(500), '500')
  assert.equal(formatContextToken(51800), '51.8K')
  assert.equal(formatContextToken(168000), '168K')
  assert.equal(formatContextToken(1000000), '1M')
  assert.equal(formatContextToken(2560000), '2.56M')
})

test('calculateContextRatio: 比例计算与上下界限制', () => {
  assert.equal(calculateContextRatio(50, 100), 0.5)
  assert.equal(calculateContextRatio(150, 100), 1.0)
  assert.equal(calculateContextRatio(-10, 100), 0)
  assert.equal(calculateContextRatio(50, null), 0)
  assert.equal(calculateContextRatio(50, 0), 0)
  assert.equal(calculateContextRatio(50, 100, 0.308), 0.308)
  assert.equal(calculateContextRatio(50, 100, 1.5), 1.0)
})

test('formatContextUsageTooltip: 生成规范的上下文使用提示文本', () => {
  assert.equal(
    formatContextUsageTooltip({
      usedTokens: 51800,
      limitTokens: 168000,
      ratio: 51800 / 168000
    }),
    '30.8% · 51.8K/168K 上下文已使用'
  )

  assert.equal(
    formatContextUsageTooltip({
      usedTokens: 0,
      limitTokens: 128000
    }),
    '0.0% · 0/128K 上下文已使用'
  )

  assert.equal(
    formatContextUsageTooltip({
      usedTokens: 1200,
      limitTokens: null
    }),
    '1.2K 上下文已使用'
  )

  assert.equal(
    formatContextUsageTooltip({
      usedTokens: 0,
      limitTokens: null
    }),
    '0.0% · 0 上下文已使用'
  )

  assert.equal(
    formatContextUsageTooltip({
      customTitle: '自定义提示'
    }),
    '自定义提示'
  )
})

test('getContextUsageTone: 根据占比返回正常/警告/危险色调', () => {
  assert.equal(getContextUsageTone(0.3), 'is-normal')
  assert.equal(getContextUsageTone(0.74), 'is-normal')
  assert.equal(getContextUsageTone(0.75), 'is-warning')
  assert.equal(getContextUsageTone(0.89), 'is-warning')
  assert.equal(getContextUsageTone(0.9), 'is-danger')
  assert.equal(getContextUsageTone(1.0), 'is-danger')
})

test('resolveContextPressureTokens: 优先使用回复完成后的下一轮估算', () => {
  assert.equal(resolveContextPressureTokens({ next_llm_input_tokens: 170, llm_input_tokens: 120 }), 170)
  assert.equal(resolveContextPressureTokens({ llm_input_tokens: 120 }), 120)
  assert.equal(resolveContextPressureTokens({ next_llm_input_tokens: null }), null)
  assert.equal(resolveContextPressureTokens(null), null)
})

test('shouldSuggestContextCompression: 只在达到 85% 派生提示线时建议压缩', () => {
  assert.equal(shouldSuggestContextCompression(0.849), false)
  assert.equal(shouldSuggestContextCompression(0.85), true)
})
