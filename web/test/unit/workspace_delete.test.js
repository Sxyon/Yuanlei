import assert from 'node:assert/strict'
import test from 'node:test'

import { deleteWorkspaceEntries } from '../../src/utils/workspaceDelete.js'

const symlinkConflict = () => ({
  response: {
    status: 409,
    data: { detail: { code: 'workspace_contains_symlinks' } }
  }
})

test('固定 symlink 冲突确认前不发送安全删除，确认后才使用安全参数重试', async () => {
  const calls = []
  let resolveConfirmation
  const confirmation = new Promise((resolve) => {
    resolveConfirmation = resolve
  })
  const operation = deleteWorkspaceEntries({
    entries: [{ path: '/repository' }],
    deletePath: async (path, options) => {
      calls.push([path, options])
      if (!options.safeUnlinkSymlinks) throw symlinkConflict()
    },
    confirmSafeCleanup: () => confirmation
  })

  await Promise.resolve()
  await Promise.resolve()
  assert.deepEqual(calls, [['/repository', { safeUnlinkSymlinks: false }]])

  resolveConfirmation(true)
  const result = await operation

  assert.deepEqual(calls, [
    ['/repository', { safeUnlinkSymlinks: false }],
    ['/repository', { safeUnlinkSymlinks: true }]
  ])
  assert.deepEqual(result, { deletedPaths: ['/repository'], cancelled: false })
})

test('取消 symlink 安全清理不会发送重试请求', async () => {
  const calls = []
  const result = await deleteWorkspaceEntries({
    entries: [{ path: '/repository' }],
    deletePath: async (path, options) => {
      calls.push([path, options])
      throw symlinkConflict()
    },
    confirmSafeCleanup: async () => false
  })

  assert.deepEqual(calls, [['/repository', { safeUnlinkSymlinks: false }]])
  assert.deepEqual(result, { deletedPaths: [], cancelled: true })
})

test('其他 409 不显示安全清理确认并保持原错误', async () => {
  const otherConflict = {
    response: { status: 409, data: { detail: { code: 'other_conflict' } } }
  }
  let confirmations = 0

  await assert.rejects(
    deleteWorkspaceEntries({
      entries: [{ path: '/repository' }],
      deletePath: async () => {
        throw otherConflict
      },
      confirmSafeCleanup: async () => {
        confirmations += 1
        return true
      }
    }),
    (error) => error === otherConflict
  )
  assert.equal(confirmations, 0)
})
