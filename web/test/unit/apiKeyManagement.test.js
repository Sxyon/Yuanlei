import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { webcrypto } from 'node:crypto'
import { runInNewContext } from 'node:vm'
import test from 'node:test'
import { parse } from 'vue/compiler-sfc'
import { reactive, ref } from 'vue'

const source = readFileSync(
  new URL('../../src/components/ApiKeyManagementComponent.vue', import.meta.url),
  'utf8'
)
const storageKey = 'yuxi_pending_api_key_request_id'

/** 在无 randomUUID 的环境执行真实组件脚本。 */
function setupComponent({
  storage = new Map(),
  create = async () => ({ secret: 'test-secret' })
} = {}) {
  const { descriptor } = parse(source)
  const script = descriptor.scriptSetup.content.replace(/^import .* from .*$/gm, '')
  return runInNewContext(
    `${script}\n;({ showCreateModal, handleCreate, handleCreateCancel, createForm, createRequestId, createModalVisible, secretModalVisible, createdSecret })`,
    {
      ref,
      reactive,
      onMounted: () => {},
      crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
      sessionStorage: {
        getItem: (key) => storage.get(key) ?? null,
        setItem: (key, value) => storage.set(key, value),
        removeItem: (key) => storage.delete(key)
      },
      apikeyApi: { create, list: async () => ({ api_keys: [] }) },
      message: { error: () => {} }
    }
  )
}

test('HTTP 环境打开创建弹窗，重试复用请求 ID，成功后清除', async () => {
  const storage = new Map()
  const requests = []
  const component = setupComponent({
    storage,
    create: async (data) => {
      requests.push({ ...data })
      if (requests.length === 1) throw new Error('响应中断')
      return { secret: 'test-secret' }
    }
  })
  component.showCreateModal()
  assert.equal(component.createModalVisible.value, true)
  const id = storage.get(storageKey)
  assert.match(id, /^[0-9a-f]{32}$/)
  component.createForm.name = 'test-key'
  await component.handleCreate()
  assert.equal(storage.get(storageKey), id)
  assert.equal(component.createModalVisible.value, true)
  await component.handleCreate()
  assert.equal(requests[0].request_id, id)
  assert.equal(requests[1].request_id, id)
  assert.equal(storage.has(storageKey), false)
  assert.equal(component.secretModalVisible.value, true)
  assert.equal(component.createdSecret.value, 'test-secret')
})

test('已有 UUID 请求 ID 在重新打开弹窗时保留，取消后生成新 ID', () => {
  const existing = '36b8f84d-df4e-4d49-b662-bcde71a8764f'
  const storage = new Map([[storageKey, existing]])
  const component = setupComponent({ storage })
  component.showCreateModal()
  assert.equal(component.createRequestId.value, existing)
  component.handleCreateCancel()
  assert.equal(storage.has(storageKey), false)
  component.showCreateModal()
  const first = component.createRequestId.value
  assert.match(first, /^[0-9a-f]{32}$/)
  component.handleCreateCancel()
  component.showCreateModal()
  assert.notEqual(component.createRequestId.value, first)
})
