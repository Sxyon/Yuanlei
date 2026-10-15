import assert from 'node:assert/strict'
import { after, before, test } from 'node:test'
import { createServer } from 'vite'
let vite, api, load
before(async () => {
  vite = await createServer({ server: { middlewareMode: true, hmr: false }, appType: 'custom' })
  ;({ projectApi: api } = await vite.ssrLoadModule('/src/apis/project_api.js'))
  ;({ loadProjectGitAttention: load } = await vite.ssrLoadModule('/src/utils/projectGitAttention.js'))
})
after(async () => { await vite?.close() })
test('待审批超过一页仍全部展示，已释放占用不进入总览', async t => {
  t.mock.method(api, 'getGitOccupancies', async () => [{ id:'active',status:'owned' },{ id:'queue',status:'queued' },{ id:'old',status:'released' }])
  t.mock.method(api, 'getGitActions', async (_project, options) => {
    assert.equal(options.status, 'pending')
    return Array.from({ length:options.offset === 0 ? 100 : 1 }, (_, i) => ({id:String(options.offset+i),status:'pending'}))
  })
  const result = await load('project')
  assert.equal(result.pending.length, 101)
  assert.deepEqual(result.occupancies.map(row=>row.id), ['active','queue'])
})
test('读取失败不能伪装成没有待审批', async t => {
  t.mock.method(api, 'getGitOccupancies', async () => [])
  t.mock.method(api, 'getGitActions', async () => { throw new Error('denied') })
  await assert.rejects(load('project'), /denied/)
})

test('总览次栏占用与主栏审批各自读取，不互相阻塞或重复请求', async t => {
  const occupancies = t.mock.method(api, 'getGitOccupancies', async () => [{id:'slot', status:'owned'}])
  const actions = t.mock.method(api, 'getGitActions', async () => [{id:'pending', status:'pending'}])
  const right = await load('project', 'occupancies')
  assert.equal(right.occupancies.length, 1)
  assert.equal(actions.mock.calls.length, 0)
  const main = await load('project', 'approvals')
  assert.equal(main.pending.length, 1)
  assert.equal(occupancies.mock.calls.length, 1)
})
