import assert from 'node:assert/strict'
import { readFileSync, unlinkSync, writeFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { compileScript, parse } from 'vue/compiler-sfc'
import { createRenderer, h, nextTick, ref } from 'vue'
import { createServer } from 'vite'

function createHostNode(type) {
  return { type, props: {}, children: [], parent: null, text: '' }
}

const renderer = createRenderer({
  createElement: createHostNode,
  createText(text) {
    const node = createHostNode('text')
    node.text = text
    return node
  },
  createComment(text) {
    const node = createHostNode('comment')
    node.text = text
    return node
  },
  insert(child, parent, anchor = null) {
    child.parent = parent
    const index = anchor ? parent.children.indexOf(anchor) : -1
    if (index >= 0) parent.children.splice(index, 0, child)
    else parent.children.push(child)
  },
  remove(child) {
    const index = child.parent?.children.indexOf(child) ?? -1
    if (index >= 0) child.parent.children.splice(index, 1)
  },
  setText(node, text) {
    node.text = text
  },
  setElementText(node, text) {
    node.text = text
    node.children = []
  },
  parentNode(node) {
    return node.parent
  },
  nextSibling(node) {
    const siblings = node.parent?.children || []
    return siblings[siblings.indexOf(node) + 1] || null
  },
  patchProp(node, key, _previous, value) {
    node.props[key] = value
  }
})

function findNodes(node, predicate, result = []) {
  if (predicate(node)) result.push(node)
  for (const child of node.children || []) findNodes(child, predicate, result)
  return result
}

const ModalStub = {
  inheritAttrs: false,
  props: { open: Boolean },
  emits: ['update:open', 'cancel', 'ok'],
  setup(_props, { slots, emit }) {
    return () =>
      h('modal-shell', { props: { confirm: () => emit('ok') } }, [
        slots.default?.(),
        h('button', { id: 'confirm-btn', onClick: () => emit('ok') })
      ])
  }
}

test('个人空间文件选择器加载个人空间树，确认时携带 workspace 来源', async () => {
  globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} }
  const treeCalls = []
  const workspaceTree = {
    '/': {
      entries: [
        { path: '/docs/', name: 'docs', is_dir: true, size: 0 },
        { path: '/README.md', name: 'README.md', is_dir: false, size: 10 }
      ]
    },
    '/docs': {
      entries: [{ path: '/docs/需求.md', name: '需求.md', is_dir: false, size: 8 }]
    }
  }

  const workspaceApiStubPath = fileURLToPath(
    new URL('./__project_picker_workspace_api.mjs', import.meta.url)
  )
  const compiledModalPath = fileURLToPath(
    new URL('./__project_picker_compiled_modal.mjs', import.meta.url)
  )
  writeFileSync(
    workspaceApiStubPath,
    `export const getWorkspaceTree = (path) => { globalThis.__treeCalls.push(path); return Promise.resolve(globalThis.__workspaceTree[path] || { entries: [] }) }`
  )
  const source = readFileSync(
    new URL('../../src/components/ProjectFilePickerModal.vue', import.meta.url),
    'utf8'
  )
  const { descriptor } = parse(source)
  writeFileSync(
    compiledModalPath,
    compileScript(descriptor, { id: 'project-file-picker-test', inlineTemplate: true }).content
  )

  const server = await createServer({
    server: { middlewareMode: true, hmr: false },
    appType: 'custom',
    resolve: {
      alias: [
        { find: '@lucide/vue', replacement: '\0virtual:lucide' },
        { find: '@/components/FileTreeComponent.vue', replacement: '\0virtual:tree' },
        { find: '@/apis/workspace_api', replacement: workspaceApiStubPath }
      ]
    },
    plugins: [
      {
        name: 'project-file-picker-test',
        enforce: 'pre',
        resolveId(id) {
          if (id === '\0virtual:lucide') return id
          if (id === '\0virtual:tree') return id
        },
        load(id) {
          if (id === '\0virtual:lucide') return 'export const X = { name: "X", render: () => null }'
          if (id === '\0virtual:tree') {
            return `
              import { h } from 'vue'
              export default {
                name: 'FileTreeComponent',
                props: { treeData: Array, loadData: Function, selectedKeys: Array, expandedKeys: Array },
                emits: ['update:selectedKeys', 'update:expandedKeys', 'nodeClick'],
                setup(props, { slots }) {
                  return () => {
                    const rows = []
                    const renderRows = (nodes, depth) => {
                      for (const node of nodes || []) {
                        rows.push(
                          h('tree-row', { node, loadData: props.loadData, depth }, [
                            slots.actions ? slots.actions({ node }) : null
                          ])
                        )
                        renderRows(node.children, depth + 1)
                      }
                    }
                    renderRows(props.treeData, 0)
                    return h('tree-stub', { selectedKeys: props.selectedKeys, treeData: props.treeData }, rows)
                  }
                }
              }
            `
          }
        }
      }
    ]
  })

  globalThis.__treeCalls = treeCalls
  globalThis.__workspaceTree = workspaceTree

  let app
  try {
    const { default: Picker } = await server.ssrLoadModule(compiledModalPath)
    const host = createHostNode('root')
    const open = ref(false)
    const selections = []
    app = renderer.createApp(() =>
      h(Picker, {
        open: open.value,
        onSelect: (files) => selections.push(files),
        onCancel: () => {}
      })
    )
    app.component('a-modal', ModalStub)
    app.mount(host)

    const treeStub = () => findNodes(host, (node) => node.type === 'tree-stub')[0]
    const rowFor = (filePath) =>
      findNodes(host, (node) => node.type === 'tree-row' && node.props?.node?.key === filePath)[0]
    const findButtons = (row) => {
      const buttons = []
      const walk = (node) => {
        if (node.type === 'button') buttons.push(node)
        for (const child of node.children || []) walk(child)
      }
      walk(row)
      return buttons
    }
    const confirmButton = () =>
      findNodes(host, (node) => node.props?.id === 'confirm-btn' || node.id === 'confirm-btn')[0]

    assert.equal(treeStub(), undefined)
    assert.deepEqual(treeCalls, [])

    open.value = true
    await nextTick()
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.deepEqual(treeCalls, ['/'], '打开面板只请求个人空间根，不依赖线程')

    const rootTree = treeStub().props
    assert.deepEqual(
      rootTree.treeData.map((node) => node.key),
      ['/docs', '/README.md']
    )
    assert.equal(
      findButtons(rowFor('/docs')).length,
      0,
      '目录节点不渲染选择按钮'
    )

    const folderNode = rootTree.treeData.find((node) => node.key === '/docs')
    const folderRow = rowFor('/docs')
    await folderRow.props.loadData(folderNode)
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 0))
    assert.deepEqual(treeCalls, ['/', '/docs'])
    assert.deepEqual(
      treeStub().props.treeData.find((node) => node.key === '/docs').children.map((n) => n.key),
      ['/docs/需求.md']
    )

    confirmButton().props.onClick()
    await nextTick()
    assert.equal(selections.length, 0, '未选择文件时确认不应输出')

    const fileRow = rowFor('/docs/需求.md')
    const fileButtons = findButtons(fileRow)
    assert.equal(fileButtons.length, 1, '文件节点应渲染选择按钮')
    fileButtons[0].props.onClick({ stopPropagation() {} })
    await nextTick()
    assert.deepEqual(treeStub().props.selectedKeys, ['/docs/需求.md'])

    confirmButton().props.onClick()
    await nextTick()
    assert.deepEqual(
      selections,
      [[{ path: '/docs/需求.md', name: '需求.md', source: 'workspace' }]],
      '确认输出个人空间 scope 路径并标记 workspace 来源'
    )
  } finally {
    app?.unmount()
    await server.close()
    delete globalThis.__treeCalls
    delete globalThis.__workspaceTree
    for (const path of [workspaceApiStubPath, compiledModalPath]) {
      try {
        unlinkSync(path)
      } catch {
        // 临时文件不存在时无需处理
      }
    }
  }
})
