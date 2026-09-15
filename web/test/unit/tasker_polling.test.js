import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'
import { readFileSync } from 'node:fs'
import { compileScript, parse } from 'vue/compiler-sfc'

const deferred = () => {
  let resolve
  const promise = new Promise((done) => {
    resolve = done
  })
  return { promise, resolve }
}

test('任务请求时序与轮询生命周期', async (t) => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  const server = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  })
  const { useUserStore } = await server.ssrLoadModule('/src/stores/user.js')
  const { useTaskerStore } = await server.ssrLoadModule('/src/stores/tasker.js')
  const { taskerApi } = await server.ssrLoadModule('/src/apis/tasker.js')
  const stores = []
  const makeStore = () => {
    setActivePinia(createPinia())
    const user = useUserStore()
    user.token = 'test-session'
    user.userRole = 'admin'
    const store = useTaskerStore()
    stores.push(store)
    return { store, user }
  }
  try {
    await t.test('图谱构建和重试的旧提交回执不能进入新会话', async () => {
      const source = readFileSync(
        new URL('../../src/components/KnowledgeGraphSection.vue', import.meta.url),
        'utf8'
      )
      const { descriptor } = parse(source)
      const { scriptSetupAst } = compileScript(descriptor, { id: 'graph-task-test' })
      for (const [name, apiMethod] of [
        ['startGraphBuild', 'startIndex'],
        ['retryGraphVectors', 'reconcile']
      ]) {
        const node = scriptSetupAst.find(
          (node) =>
            node.type === 'VariableDeclaration' &&
            node.declarations.some((item) => item.id.name === name)
        )
        assert.ok(node, name)
        const { store, user } = makeStore()
        const response = deferred()
        const action = new Function(
          'taskerStore',
          'graphBuildApi',
          'kbId',
          'message',
          'GRAPH_BUILD_TASK_TYPE',
          'loadGraphBuildStatus',
          'getErrorDetail',
          descriptor.scriptSetup.content.slice(node.start, node.end) + `; return ${name}`
        )(
          store,
          { [apiMethod]: () => response.promise },
          { value: 'test-kb' },
          { success() {}, error: assert.fail },
          'graph-build',
          async () => {},
          (error) => error.message
        )
        const pending = action()
        user.logout()
        user.token = 'next-session'
        user.userRole = 'admin'
        response.resolve({ task_id: 'old-graph-task' })
        await pending
        assert.deepEqual(store.tasks, [])
        await action()
        assert.equal(store.tasks[0].id, 'old-graph-task')
        store.reset()
      }
    })
    await t.test('旧提交回执不能登记到新会话，新提交仍可登记', () => {
      const { store, user } = makeStore()
      const registerOldTask = store.createTaskRegistration()
      user.logout()
      user.token = 'next-session'
      user.userRole = 'admin'
      registerOldTask({ task_id: 'old-task' })
      assert.deepEqual(store.tasks, [])
      store.createTaskRegistration()({ task_id: 'new-task' })
      assert.equal(store.tasks[0].id, 'new-task')
      store.reset()
    })
    await t.test('隐藏页面跳过轮询，恢复可见后继续读取', async (t) => {
      const { store } = makeStore()
      t.mock.timers.enable({ apis: ['setTimeout'] })
      globalThis.document = { visibilityState: 'hidden' }
      let calls = 0
      taskerApi.fetchTasks = async () => {
        calls++
        return { tasks: [] }
      }
      try {
        store.openDrawer()
        t.mock.timers.tick(10000)
        assert.equal(calls, 0)
        document.visibilityState = 'visible'
        t.mock.timers.tick(5000)
        assert.equal(calls, 1)
        store.reset()
      } finally {
        delete globalThis.document
      }
    })
    await t.test('已入队任务不会被更早开始的列表抹去', async () => {
      const { store } = makeStore()
      const response = deferred()
      taskerApi.fetchTasks = () => response.promise
      const loading = store.loadTasks()
      store.createTaskRegistration()({ task_id: 'new-task' })
      response.resolve({ tasks: [] })
      await loading
      assert.equal(store.tasks[0].id, 'new-task')
      assert.equal(store.loading, false)
      store.reset()
    })
    await t.test('退出登录后详情请求不能回写，晚到旧详情不能覆盖新详情', async () => {
      const { store, user } = makeStore()
      const old = deferred(),
        latest = deferred()
      let calls = 0
      taskerApi.fetchTaskDetail = () => (++calls === 1 ? old.promise : latest.promise)
      const first = store.refreshTask('task'),
        second = store.refreshTask('task')
      latest.resolve({ task: { id: 'task', status: 'success' } })
      await second
      old.resolve({ task: { id: 'task', status: 'running' } })
      await first
      assert.equal(store.tasks[0].status, 'success')
      const afterLogout = deferred()
      taskerApi.fetchTaskDetail = () => afterLogout.promise
      const pending = store.refreshTask('task')
      user.logout()
      afterLogout.resolve({ task: { id: 'task', status: 'running' } })
      await pending
      assert.deepEqual(store.tasks, [])
    })
    await t.test('详情更新后旧列表不能恢复过期内容', async () => {
      const { store } = makeStore()
      const response = deferred()
      taskerApi.fetchTasks = () => response.promise
      taskerApi.fetchTaskDetail = async () => ({ task: { id: 'task', status: 'success' } })
      const loading = store.loadTasks()
      await store.refreshTask('task')
      response.resolve({ tasks: [{ id: 'task', status: 'running' }] })
      await loading
      assert.equal(store.tasks[0].status, 'success')
      store.reset()
    })
    await t.test('旧详情响应不能覆盖较新的列表终态', async () => {
      const { store } = makeStore()
      const response = deferred()
      taskerApi.fetchTaskDetail = () => response.promise
      taskerApi.fetchTasks = async () => ({ tasks: [{ id: 'task', status: 'success' }] })
      const pending = store.refreshTask('task')
      await store.loadTasks()
      response.resolve({ task: { id: 'task', status: 'running' } })
      await pending
      assert.equal(store.tasks[0].status, 'success')
      store.reset()
    })
    await t.test('切换账号后旧取消与删除回调不操作新会话', async () => {
      const { store, user } = makeStore()
      const cancelled = deferred(),
        deleted = deferred()
      taskerApi.cancelTask = () => cancelled.promise
      taskerApi.deleteTask = () => deleted.promise
      taskerApi.fetchTaskDetail = () => assert.fail('旧会话不能启动详情读取')
      const cancel = store.cancelTask('task'),
        remove = store.deleteTask('task')
      user.logout()
      user.token = 'next-session'
      user.userRole = 'admin'
      store.createTaskRegistration()({ task_id: 'task' })
      cancelled.resolve({})
      deleted.resolve({})
      await Promise.all([cancel, remove])
      assert.equal(store.tasks[0].status, 'queued')
      assert.equal(store.lastError, null)
      store.reset()
    })
    await t.test('请求失败保留最近成功状态并退避', async (t) => {
      const { store } = makeStore()
      t.mock.timers.enable({ apis: ['setTimeout'] })
      t.mock.method(console, 'error', () => {})
      taskerApi.fetchTasks = async () => ({
        tasks: [{ id: 'task', status: 'running' }],
        summary: { total: 1, status_counts: { running: 1 } }
      })
      await store.loadTasks()
      let calls = 0
      taskerApi.fetchTasks = async () => {
        calls++
        throw new Error('offline')
      }
      await store.loadTasks()
      assert.equal(store.activeCount, 1)
      assert.equal(store.tasks[0].id, 'task')
      assert.equal(store.lastError.message, 'offline')
      t.mock.timers.tick(9999)
      assert.equal(calls, 1)
      t.mock.timers.tick(1)
      assert.equal(calls, 2)
      store.reset()
    })
    await t.test('旧列表响应不能覆盖新终态', async () => {
      const { store } = makeStore()
      const old = deferred(),
        latest = deferred()
      let calls = 0
      taskerApi.fetchTasks = () => (++calls === 1 ? old.promise : latest.promise)
      const first = store.loadTasks(),
        second = store.loadTasks()
      latest.resolve({ tasks: [{ id: 't', status: 'success' }] })
      await second
      old.resolve({ tasks: [{ id: 't', status: 'running' }] })
      await first
      assert.equal(store.tasks[0].status, 'success')
      store.reset()
    })
    await t.test('退出登录使在途响应失效并立即清空状态', async () => {
      const { store, user } = makeStore()
      const response = deferred()
      taskerApi.fetchTasks = () => response.promise
      store.createTaskRegistration()({ task_id: 'queued' })
      const loading = store.loadTasks()
      user.logout()
      response.resolve({ tasks: [{ id: 'private-task', status: 'running' }] })
      await loading
      assert.deepEqual(store.tasks, [])
      assert.equal(store.loading, false)
      store.reset()
    })
    await t.test('慢请求期间不产生重叠轮询，完成后才安排下一轮', async (t) => {
      const { store } = makeStore()
      t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] })
      const response = deferred()
      let calls = 0
      taskerApi.fetchTasks = () => {
        calls++
        return response.promise
      }
      store.openDrawer()
      t.mock.timers.tick(5000)
      assert.equal(calls, 1)
      t.mock.timers.tick(15000)
      assert.equal(calls, 1)
      response.resolve({ tasks: [] })
      await Promise.resolve()
      await Promise.resolve()
      t.mock.timers.tick(4999)
      assert.equal(calls, 1)
      t.mock.timers.tick(1)
      assert.equal(calls, 2)
      store.reset()
      t.mock.timers.tick(10000)
      assert.equal(calls, 2)
    })
  } finally {
    stores.forEach((store) => store.$dispose())
    await server.close()
  }
})
