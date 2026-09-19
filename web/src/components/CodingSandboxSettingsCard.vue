<template>
  <div class="coding-sandbox-settings">
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">专属沙盒</div>
        <p class="section-description">
          查看当前用户的 Agent 专属沙盒状态与配额；可手动预热、回收 runtime 或按当前配置重建。预热与重建不会删除 Workdir 文件。
        </p>
      </div>
      <div class="header-actions">
        <a-button
          class="refresh-btn lucide-icon-btn"
          :loading="loading"
          title="刷新"
          @click="loadSandboxes"
        >
          <template #icon><RefreshCw :size="16" :class="{ spin: loading }" /></template>
        </a-button>
      </div>
    </div>

    <div class="quota-row" v-if="quota">
      <span>专属：{{ quota.dedicated_used }} / {{ quota.dedicated_max_per_user }}</span>
      <span>常驻：{{ quota.resident_used }} / {{ quota.resident_max_per_user }}</span>
      <span>活跃：{{ quota.active }}</span>
    </div>

    <a-spin :spinning="loading">
      <div v-if="sandboxes.length" class="sandbox-list">
        <div v-for="item in sandboxes" :key="item.scope_key" class="sandbox-item">
          <div class="sandbox-meta">
            <span class="sandbox-agent">{{ item.agent_slug }}</span>
            <span class="sandbox-status" :class="item.status">{{ item.status }}</span>
            <span class="sandbox-lifecycle">{{ item.lifecycle }}</span>
            <span class="sandbox-time">最后活动 {{ item.last_activity_at || '—' }}</span>
            <span class="sandbox-lease" v-if="item.lease_owner_kind">
              租约 {{ item.lease_owner_kind }}
            </span>
          </div>
          <div class="sandbox-actions">
            <a-button size="small" :loading="busyKey === item.scope_key" @click="provision(item)">
              预热
            </a-button>
            <a-button size="small" :loading="busyKey === item.scope_key" @click="suspend(item)">
              回收
            </a-button>
            <a-button
              size="small"
              type="primary"
              :loading="busyKey === item.scope_key"
              @click="rebuild(item)"
            >
              重建
            </a-button>
          </div>
        </div>
      </div>
      <a-empty v-else :image="simpleImage" description="当前没有专属沙盒" />
    </a-spin>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { Empty, message, Modal } from 'ant-design-vue'
import { RefreshCw } from '@lucide/vue'
import { codingSandboxApi } from '@/apis/coding_sandbox_api'

const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE
const loading = ref(false)
const busyKey = ref('')
const sandboxes = ref([])
const quota = ref(null)

const loadSandboxes = async () => {
  loading.value = true
  try {
    const data = await codingSandboxApi.list()
    sandboxes.value = Array.isArray(data?.sandboxes) ? data.sandboxes : []
    quota.value = data?.quota || null
  } catch (error) {
    message.error(error?.message || '加载专属沙盒失败')
  } finally {
    loading.value = false
  }
}

const runAction = async (item, action) => {
  busyKey.value = item.scope_key
  try {
    await action(item.agent_slug, item.project_id)
    message.success('操作已提交')
    await loadSandboxes()
  } catch (error) {
    message.error(error?.message || '操作失败')
  } finally {
    busyKey.value = ''
  }
}

const suspend = (item) => runAction(item, codingSandboxApi.suspend)

const provision = (item) => {
  Modal.confirm({
    title: '预热专属沙盒',
    content: '将按当前配置创建或恢复 runtime；已有 runtime 会复用，Workdir 文件不会丢失。继续？',
    okText: '预热',
    cancelText: '取消',
    onOk: () => runAction(item, codingSandboxApi.provision)
  })
}

const rebuild = (item) => {
  Modal.confirm({
    title: '重建专属沙盒',
    content: '将回收当前 runtime 并按当前配置与凭据重建，Workdir 文件不会丢失。继续？',
    okText: '重建',
    cancelText: '取消',
    onOk: () => runAction(item, codingSandboxApi.rebuild)
  })
}

onMounted(loadSandboxes)
</script>

<style scoped>
.coding-sandbox-settings {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #1f2329);
}

.section-description {
  margin: 4px 0 0;
  color: var(--text-secondary, #646a73);
  font-size: 13px;
}

.quota-row {
  display: flex;
  gap: 18px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--fill-quaternary, #f5f6f7);
  font-size: 13px;
  color: var(--text-secondary, #646a73);
}

.sandbox-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sandbox-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--border-primary, #dee0e3);
  border-radius: 6px;
}

.sandbox-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 13px;
}

.sandbox-status.active {
  color: var(--color-success, #34c759);
}

.sandbox-status.suspended {
  color: var(--text-secondary, #646a73);
}

.sandbox-status.error {
  color: var(--color-error, #ff4d4f);
}

.sandbox-actions {
  display: flex;
  gap: 8px;
}

.spin {
  animation: coding-sandbox-spin 1s linear infinite;
}

@keyframes coding-sandbox-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
