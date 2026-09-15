import assert from 'node:assert/strict'
import test from 'node:test'
import { createMarkdownRenderCache } from '../../src/utils/markdownRenderCache.js'

test('缓存按原文和 HTML 总字符预算淘汰，命中保留最近使用项', () => {
  const cache = createMarkdownRenderCache({ maxChars: 12, maxEntries: 100 })
  cache.set('a', '111')
  cache.set('b', '222')
  cache.set('c', '333')
  assert.equal(cache.get('a'), '111')
  cache.set('d', '444')
  assert.equal(cache.get('b'), undefined)
  assert.equal(cache.get('a'), '111')
  assert.equal(cache.get('c'), '333')
  assert.equal(cache.get('d'), '444')
})

test('超过预算的单条不缓存，替换按新大小计量', () => {
  const cache = createMarkdownRenderCache({ maxChars: 10, maxEntries: 3 })
  cache.set('a', '1')
  cache.set('b', '2')
  cache.set('a', '1234567')
  assert.equal(cache.get('b'), '2')
  cache.set('a', '1234567890')
  assert.equal(cache.get('a'), undefined)
  assert.equal(cache.get('b'), '2')
  cache.set('c', '1234567')
  assert.equal(cache.get('b'), '2')
  assert.equal(cache.get('c'), '1234567')
})

test('空 HTML 可命中，同时遵守条数上限', () => {
  const cache = createMarkdownRenderCache({ maxChars: 100, maxEntries: 1 })
  cache.set('a', '')
  assert.equal(cache.get('a'), '')
  cache.set('b', 'result')
  assert.equal(cache.get('a'), undefined)
  assert.equal(cache.get('b'), 'result')
})
