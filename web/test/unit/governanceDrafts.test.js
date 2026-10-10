import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getGovernanceDraft, setGovernanceDraft, clearGovernanceDrafts } from '../../src/utils/governanceDrafts.js'

test('草稿按身份、项目和准确对象隔离，读取副本不能修改缓存', () => {
  clearGovernanceDrafts()
  const value = { reason: '未提交', expected_revision: 2 }
  setGovernanceDraft('u1', 'p1', 'decision:d1', value)
  value.reason = '外部修改'
  const restored = getGovernanceDraft('u1', 'p1', 'decision:d1')
  assert.equal(restored.reason, '未提交')
  restored.expected_revision = 99
  assert.equal(getGovernanceDraft('u1', 'p1', 'decision:d1').expected_revision, 2)
  for (const [u, p, o] of [['u2', 'p1', 'decision:d1'], ['u1', 'p2', 'decision:d1'], ['u1', 'p1', 'decision:d2']]) assert.equal(getGovernanceDraft(u, p, o), null)
})
test('成功只清准确对象，无权清项目，登出清全部，存储失败不阻断', () => {
  globalThis.sessionStorage = { setItem() { throw new Error('disabled') }, removeItem() { throw new Error('disabled') } }
  for (const [u, p, o] of [['u1', 'p1', 'a'], ['u1', 'p1', 'b'], ['u1', 'p2', 'a'], ['u2', 'p1', 'a']]) setGovernanceDraft(u, p, o, { reason: o })
  setGovernanceDraft('u1', 'p1', 'a', null)
  assert.equal(getGovernanceDraft('u1', 'p1', 'a'), null)
  assert.equal(getGovernanceDraft('u1', 'p1', 'b').reason, 'b')
  clearGovernanceDrafts('u1', 'p1')
  assert.equal(getGovernanceDraft('u1', 'p1', 'b'), null)
  assert.ok(getGovernanceDraft('u1', 'p2', 'a'))
  assert.ok(getGovernanceDraft('u2', 'p1', 'a'))
  clearGovernanceDrafts()
  assert.equal(getGovernanceDraft('u2', 'p1', 'a'), null)
  delete globalThis.sessionStorage
})
