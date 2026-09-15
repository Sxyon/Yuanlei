import assert from 'node:assert/strict'
import test from 'node:test'

import { formatMysqlResult } from '../../src/components/ToolCallingResult/tools/mysqlResultFormatter.js'

test('formatMysqlResult 将空值保持为空字符串', () => {
  assert.equal(formatMysqlResult(undefined), '')
  assert.equal(formatMysqlResult(null), '')
  assert.equal(formatMysqlResult(''), '')
  assert.equal(formatMysqlResult(false), '')
  assert.equal(formatMysqlResult(0), '')
})

test('formatMysqlResult 格式化合法 JSON 字符串并保留非法 JSON', () => {
  assert.equal(
    formatMysqlResult('{"name":"users","count":2}'),
    '{\n  "name": "users",\n  "count": 2\n}'
  )
  assert.equal(formatMysqlResult('{not-json'), '{not-json')
})

test('formatMysqlResult 格式化对象和数组', () => {
  assert.equal(formatMysqlResult({ name: 'users' }), '{\n  "name": "users"\n}')
  assert.equal(
    formatMysqlResult([1, { name: 'users' }]),
    '[\n  1,\n  {\n    "name": "users"\n  }\n]'
  )
})

test('formatMysqlResult 将非空数字按 primitive 展示', () => {
  assert.equal(formatMysqlResult(42), '42')
})
