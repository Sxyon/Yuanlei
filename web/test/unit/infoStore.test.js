import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createServer } from 'vite'

test('调试模式读取受限 LocalStorage 时降级为关闭', async () => {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem() {
        throw new DOMException('blocked', 'SecurityError')
      },
      setItem() {},
      removeItem() {}
    }
  })
  const server = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  })
  setActivePinia(createPinia())
  try {
    const { useInfoStore } = await server.ssrLoadModule('/src/stores/info.js')
    const store = useInfoStore()

    assert.equal(store.debugMode, false)
  } finally {
    await server.close()
  }
})

test('品牌配置合并并发读取，成功缓存，失败与强制刷新可重试', async (t) => {
  const server = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom'
  })
  setActivePinia(createPinia())
  try {
    const { useInfoStore } = await server.ssrLoadModule('/src/stores/info.js')
    const { brandApi } = await server.ssrLoadModule('/src/apis/system_api.js')
    const store = useInfoStore()
    const pending = []
    t.mock.method(brandApi, 'getInfoConfig', () => new Promise((resolve) => pending.push(resolve)))
    const first = store.loadInfoConfig()
    const second = store.loadInfoConfig()
    assert.equal(pending.length, 1)
    pending[0]({ success: true, data: { branding: { name: 'Test' } } })
    assert.deepEqual(await first, { branding: { name: 'Test' } })
    assert.deepEqual(await second, { branding: { name: 'Test' } })
    assert.equal(store.branding.name, 'Test')
    await store.loadInfoConfig()
    assert.equal(pending.length, 1)
    const forced = store.loadInfoConfig(true)
    assert.equal(pending.length, 2)
    pending[1]({ success: false })
    assert.equal(await forced, null)
    const retry = store.loadInfoConfig(true)
    assert.equal(pending.length, 3)
    pending[2]({ success: true, data: { branding: { name: 'New' } } })
    await retry
    assert.equal(store.branding.name, 'New')
    assert.equal(store.isLoading, false)
  } finally {
    await server.close()
  }
})
