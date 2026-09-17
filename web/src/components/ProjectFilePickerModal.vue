<template>
  <a-modal
    :open="open"
    title="从个人空间选择文件"
    ok-text="引用为附件"
    cancel-text="取消"
    :confirm-loading="confirming"
    :ok-button-props="{ disabled: !selectedFiles.length }"
    @ok="handleConfirm"
    @cancel="handleCancel"
  >
    <div class="picker-body">
      <div v-if="loading" class="picker-state">正在加载个人空间文件...</div>
      <div v-else-if="error" class="picker-state picker-error">{{ error }}</div>
      <div v-else-if="!treeData.length" class="picker-state">个人空间为空</div>
      <FileTreeComponent
        v-else
        :tree-data="treeData"
        :load-data="loadDirectory"
        :selected-keys="selectedKeys"
        :expanded-keys="expandedKeys"
        @update:selectedKeys="handleSelectedKeys"
        @update:expandedKeys="handleExpandedKeys"
        @nodeClick="handleNodeClick"
      >
        <template #actions="{ node }">
          <button
            v-if="isFile(node)"
            type="button"
            class="picker-add-btn"
            :class="{ active: isSelected(node.key) }"
            @click.stop="toggleSelect(node)"
          >
            {{ isSelected(node.key) ? '已选' : '选择' }}
          </button>
        </template>
      </FileTreeComponent>
    </div>

    <div v-if="selectedFiles.length" class="picker-selection">
      <div class="picker-selection-title">已选 {{ selectedFiles.length }} 个文件</div>
      <div v-for="file in selectedFiles" :key="file.path" class="picker-selection-item">
        <span class="picker-selection-name" :title="file.path">{{ file.name }}</span>
        <X :size="14" class="picker-selection-remove" @click="removeSelection(file)" />
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { ref, watch } from 'vue'
import { X } from '@lucide/vue'
import FileTreeComponent from '@/components/FileTreeComponent.vue'
import { getWorkspaceTree } from '@/apis/workspace_api'

const props = defineProps({
  open: {
    type: Boolean,
    default: false
  },
  confirming: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:open', 'select', 'cancel'])

const treeData = ref([])
const loading = ref(false)
const error = ref('')
const selectedFiles = ref([])
const selectedKeys = ref([])
const expandedKeys = ref([])

const isFile = (node) => node?.isLeaf === true
const isSelected = (key) => selectedFiles.value.some((file) => file.path === key)

const buildDisplayName = (fullPath) => {
  const normalized = String(fullPath || '').replace(/\/+$/, '')
  if (!normalized || normalized === '/') return '/'
  return normalized.split('/').filter(Boolean).pop() || normalized
}

const sortEntries = (entries) =>
  [...entries].sort((left, right) => {
    if (Boolean(left?.is_dir) !== Boolean(right?.is_dir)) {
      return left?.is_dir ? -1 : 1
    }
    return buildDisplayName(left?.path).localeCompare(buildDisplayName(right?.path), 'zh-Hans-CN')
  })

const createTreeNode = (entry) => {
  const fullPath = String(entry?.path || '').replace(/\/+$/, '')
  const isDir = Boolean(entry?.is_dir)
  return {
    key: fullPath,
    title: buildDisplayName(fullPath),
    isLeaf: !isDir,
    children: isDir ? [] : undefined
  }
}

const loadRoot = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await getWorkspaceTree('/')
    treeData.value = sortEntries(res?.entries || []).map(createTreeNode)
  } catch (err) {
    error.value = err?.message || '加载个人空间文件失败'
  } finally {
    loading.value = false
  }
}

const loadDirectory = async (treeNode) => {
  if (treeNode.isLeaf || treeNode.children?.length) return
  const directoryPath = treeNode?.key || '/'
  const res = await getWorkspaceTree(directoryPath)
  const children = sortEntries(res?.entries || []).map(createTreeNode)
  const updateChildren = (nodes, targetKey, nextChildren) =>
    nodes.map((node) => {
      if (node.key === targetKey) return { ...node, children: nextChildren }
      if (node.children?.length) {
        return { ...node, children: updateChildren(node.children, targetKey, nextChildren) }
      }
      return node
    })
  treeData.value = updateChildren(treeData.value, directoryPath, children)
}

const handleSelectedKeys = (keys) => {
  selectedKeys.value = keys
}

const handleExpandedKeys = (keys) => {
  expandedKeys.value = keys
}

const handleNodeClick = (node) => {
  if (isFile(node)) {
    toggleSelect(node)
  }
}

const toggleSelect = (node) => {
  if (!isFile(node)) return
  const path = node.key
  if (isSelected(path)) {
    removeSelection({ path, name: node.title })
  } else {
    selectedFiles.value = [...selectedFiles.value, { path, name: node.title }]
  }
  selectedKeys.value = selectedFiles.value.map((file) => file.path)
}

const removeSelection = (file) => {
  selectedFiles.value = selectedFiles.value.filter((item) => item.path !== file.path)
  selectedKeys.value = selectedFiles.value.map((item) => item.path)
}

const handleConfirm = () => {
  if (!selectedFiles.value.length) return
  emit(
    'select',
    selectedFiles.value.map((file) => ({ ...file, source: 'workspace' }))
  )
}

const handleCancel = () => {
  emit('update:open', false)
  emit('cancel')
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      selectedFiles.value = []
      selectedKeys.value = []
      expandedKeys.value = []
      loadRoot()
    }
  }
)
</script>

<style scoped lang="less">
.picker-body {
  min-height: 240px;
  max-height: 380px;
  overflow-y: auto;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  padding: 4px;
}

.picker-state {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  color: var(--gray-500);
  font-size: 13px;
}

.picker-error {
  color: var(--danger);
}

.picker-add-btn {
  border: 1px solid var(--main-300);
  border-radius: 6px;
  background: transparent;
  color: var(--main-600);
  font-size: 12px;
  padding: 2px 8px;
  cursor: pointer;
  line-height: 1.4;

  &.active {
    background: var(--main-500);
    color: var(--gray-0);
    border-color: var(--main-500);
  }
}

.picker-selection {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--gray-150);
}

.picker-selection-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--gray-800);
  margin-bottom: 6px;
}

.picker-selection-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 4px 0;
}

.picker-selection-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: var(--gray-700);
}

.picker-selection-remove {
  flex-shrink: 0;
  color: var(--gray-400);
  cursor: pointer;

  &:hover {
    color: var(--gray-700);
  }
}
</style>
