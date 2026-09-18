<template>
  <div class="agent-view">
    <div class="agent-view-body">
      <!-- 中间内容区域 -->
      <div class="content">
        <AgentChatComponent
          ref="chatComponentRef"
          :single-mode="false"
          :initial-project-id="routeDraftProjectId"
          :is-new-conversation="!getRouteThreadId()"
          @thread-change="handleThreadChange"
        >
          <template #header-right="{ currentThread, hasActiveThread }">
            <button
              v-if="hasActiveThread && currentThread?.status !== 'subagent'"
              type="button"
              class="task-git-button"
              title="管理当前任务使用的 Git 仓库"
              @click="openTaskRepositories(currentThread)"
            >
              <GitBranch :size="16" />
              <span>任务仓库</span>
            </button>
          </template>
          <template #input-actions-left="{ hasActiveThread, isCreatingThread }">
            <ActionDropdown
              upward
              v-if="selectedAgentId"
              v-model:open="agentDropdownOpen"
              v-model:search="agentSearchKeyword"
              search-placeholder="搜索智能体"
              :disabled="isCreatingThread"
            >
              <template #trigger>
                <ActionTrigger
                  :label="currentAgentLabel"
                  :open="agentDropdownOpen"
                  :disabled="isCreatingThread"
                  collapse-label
                >
                  <template #icon>
                    <FallbackAvatar
                      v-if="currentAgentOption"
                      :src="currentAgentOption.icon"
                      :default-src="currentAgentOption.defaultIcon"
                      :name="currentAgentOption.label"
                      :seed="currentAgentOption.value || currentAgentOption.label"
                      kind="agent"
                      :size="20"
                      shape="rounded"
                      alt=""
                    />
                  </template>
                </ActionTrigger>
              </template>
              <div v-if="!filteredAgentOptions.length" class="agent-switch-empty" role="status">
                暂无匹配智能体
              </div>
              <button
                v-for="agent in filteredAgentOptions"
                :key="agent.value"
                type="button"
                class="config-dropdown-item"
                :class="{
                  selected: agent.value === selectedAgentId,
                  disabled: hasActiveThread && agent.value !== selectedAgentId
                }"
                @click="handleAgentSwitch(agent.value, hasActiveThread, isCreatingThread)"
              >
                <FallbackAvatar
                  class="config-dropdown-item-icon-image"
                  :src="agent.icon"
                  :default-src="agent.defaultIcon"
                  :name="agent.label"
                  :seed="agent.value || agent.label"
                  kind="agent"
                  :size="24"
                  shape="rounded"
                  :alt="`${agent.label}图标`"
                />
                <span class="config-dropdown-item-label" :title="agent.label">{{
                  agent.label
                }}</span>
                <span v-if="agent.isBuiltin" class="config-dropdown-item-badge">内置</span>
                <span v-else-if="agent.isProjectAgent" class="config-dropdown-item-badge is-project">项目</span>
                <Check
                  v-if="agent.value === selectedAgentId"
                  :size="14"
                  class="config-dropdown-item-check"
                />
              </button>
              <template #footer>
                <div v-if="hasActiveThread" class="config-dropdown-hint">
                  当前对话已绑定智能体，新对话可切换。
                </div>

                <div class="config-dropdown-divider"></div>

                <div class="config-dropdown-actions">
                  <button
                    type="button"
                    class="config-dropdown-item action-item"
                    @click="openAgentManagement"
                  >
                    <Settings2 :size="15" class="config-dropdown-item-icon" />
                    <span class="config-dropdown-item-label">编辑智能体</span>
                  </button>
                  <button
                    type="button"
                    class="config-dropdown-item action-item"
                    @click="openCreateAgent"
                  >
                    <Plus :size="15" class="config-dropdown-item-icon" />
                    <span class="config-dropdown-item-label">新建智能体</span>
                  </button>
                </div>
              </template>
            </ActionDropdown>
          </template>
        </AgentChatComponent>
      </div>
    </div>
    <AgentEditModal
      ref="agentEditModalRef"
      :backend-options="agentBackendOptions"
      @saved="handleAgentSaved"
    />
    <ConversationGitRepositoriesModal
      :open="Boolean(gitModalThread)"
      :thread-id="gitModalThread?.id || ''"
      :project-id="gitModalThread?.project_id || ''"
      @update:open="(open) => !open && (gitModalThread = null)"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { Settings2, Check, GitBranch, Plus } from '@lucide/vue'
import { useRoute, useRouter } from 'vue-router'
import { agentApi } from '@/apis/agent_api'
import ActionDropdown from '@/components/common/ActionDropdown.vue'
import ActionTrigger from '@/components/common/ActionTrigger.vue'
import AgentChatComponent from '@/components/AgentChatComponent.vue'
import AgentEditModal from '@/components/model-management/AgentEditModal.vue'
import ConversationGitRepositoriesModal from '@/components/ConversationGitRepositoriesModal.vue'
import { isBuiltinAgent, useAgentStore } from '@/stores/agent'
import { handleChatError } from '@/utils/errorHandler'
import { generatePixelAvatar } from '@/utils/pixelAvatar'
import { normalizeAgentBackendOption } from '@/utils/agentConfigUtils'
import FallbackAvatar from '@/components/common/FallbackAvatar.vue'

import { storeToRefs } from 'pinia'

// 组件引用
const chatComponentRef = ref(null)
const agentEditModalRef = ref(null)
const gitModalThread = ref(null)

const openTaskRepositories = (thread) => {
  if (!thread?.id || !thread?.project_id) return
  gitModalThread.value = thread
}

// Stores
const agentStore = useAgentStore()
const route = useRoute()
const router = useRouter()

// 从 agentStore 中获取响应式状态
const { agents, selectedAgentId, isLoadingConfig } = storeToRefs(agentStore)

const syncingRouteThread = ref(false)

const getRouteThreadId = () => {
  const value = route.params.thread_id
  return typeof value === 'string' ? value : ''
}

const getRouteAgentId = () => {
  const value = route.query.agent_id
  return typeof value === 'string' ? value : ''
}

const routeDraftProjectId = computed(() => {
  if (getRouteThreadId()) return ''
  const value = route.query.project_id
  return typeof value === 'string' ? value : ''
})

const syncSelectedThreadFromRoute = async () => {
  const chatComponent = chatComponentRef.value
  if (!chatComponent?.selectThreadFromRoute) return

  const threadId = getRouteThreadId()
  syncingRouteThread.value = true
  try {
    if (!threadId && !agentStore.isInitialized) {
      await agentStore.initialize()
    }

    const ok = await chatComponent.selectThreadFromRoute(threadId)
    if (ok === null) return
    if (threadId && !ok) {
      await router.replace({ name: 'AgentComp' })
    }
  } catch (error) {
    handleChatError(error, 'load')
  } finally {
    syncingRouteThread.value = false
  }
}

const consumeRouteAgentSelection = async () => {
  const targetAgentId = getRouteAgentId()
  if (!targetAgentId || getRouteThreadId()) return

  try {
    if (!agentStore.isInitialized) {
      await agentStore.initialize()
    }

    await nextTick()
    const canSwitch = await chatComponentRef.value?.selectThreadFromRoute?.('')
    if (canSwitch === null) return
    await agentStore.selectAgent(targetAgentId, {
      projectId: chatComponentRef.value?.getSelectedProjectId?.() || routeDraftProjectId.value || null
    })
  } catch (error) {
    handleChatError(error, 'load')
  } finally {
    const nextQuery = { ...route.query }
    delete nextQuery.agent_id
    await router.replace({ name: 'AgentComp', query: nextQuery })
  }
}

watch(
  () => route.params.thread_id,
  () => {
    syncSelectedThreadFromRoute()
  },
  { immediate: true }
)

watch(
  () => route.query.agent_id,
  () => {
    consumeRouteAgentSelection()
  },
  { immediate: true }
)

watch(chatComponentRef, (instance) => {
  if (!instance) return
  syncSelectedThreadFromRoute()
})

const handleThreadChange = (threadId) => {
  if (syncingRouteThread.value) return
  const currentRouteThreadId = getRouteThreadId()
  const nextThreadId = threadId || ''
  if (currentRouteThreadId === nextThreadId) return

  if (nextThreadId) {
    router.replace({ name: 'AgentCompWithThreadId', params: { thread_id: nextThreadId } })
  } else {
    router.replace({ name: 'AgentComp' })
  }
}

const toAgentOption = (agent) => ({
  label: agent.name || agent.id,
  value: agent.id,
  icon: agent.icon || '',
  defaultIcon: agent.id ? generatePixelAvatar(agent.id) : '',
  isBuiltin: isBuiltinAgent(agent),
  isProjectAgent: !!agent.is_project_agent
})

const agentQuickSwitchOptions = computed(() => {
  const options = (agents.value || []).filter((agent) => !agent.is_subagent).map(toAgentOption)
  // 项目数字员工可能不在当前可选列表中（例如正在查看已绑定线程），保留当前选中项用于展示。
  const selected = agentStore.selectedAgent
  if (selected && !selected.is_subagent && !options.some((option) => option.value === selected.id)) {
    options.unshift(toAgentOption(selected))
  }
  return options
})

const currentAgentOption = computed(() =>
  agentQuickSwitchOptions.value.find((agent) => agent.value === selectedAgentId.value)
)

const currentAgentLabel = computed(() => {
  if (isLoadingConfig.value) return '加载中...'
  return currentAgentOption.value?.label || '智能体'
})

const agentSearchKeyword = ref('')
const filteredAgentOptions = computed(() => {
  const keyword = agentSearchKeyword.value.trim().toLocaleLowerCase()
  return agentQuickSwitchOptions.value.filter((agent) =>
    agent.label.toLocaleLowerCase().includes(keyword)
  )
})

const agentDropdownOpen = ref(false)
const agentBackendOptions = ref([])
const agentBackendsLoaded = ref(false)

const loadAgentBackends = async () => {
  if (agentBackendsLoaded.value) return
  const response = await agentApi.getAgentBackends()
  agentBackendOptions.value = (response.backends || []).map(normalizeAgentBackendOption)
  agentBackendsLoaded.value = true
}

const handleAgentSwitch = async (agentId, hasActiveThread, isCreatingThread) => {
  if (!agentId || agentId === selectedAgentId.value) return
  if (isCreatingThread) {
    message.info('正在创建新对话，请稍候')
    return
  }
  if (hasActiveThread) {
    message.info('当前对话已绑定智能体，请新建对话后切换')
    return
  }
  try {
    await agentStore.selectAgent(agentId, {
      projectId: chatComponentRef.value?.getSelectedProjectId?.() || null
    })
    agentDropdownOpen.value = false
  } catch (error) {
    console.error('切换智能体出错:', error)
    message.error('切换智能体失败')
  }
}

const handleAgentSaved = async ({ mode, agent } = {}) => {
  if (mode === 'create' && !agent?.is_subagent) {
    await chatComponentRef.value?.selectThreadFromRoute?.('')
  }

  const projectId = chatComponentRef.value?.getSelectedProjectId?.() || null
  if (chatComponentRef.value?.refreshAgentsForProjectContext) {
    await chatComponentRef.value.refreshAgentsForProjectContext()
  } else {
    await agentStore.fetchAgents({ projectId })
  }
  if (selectedAgentId.value) {
    await agentStore.fetchAgentDetail(selectedAgentId.value, true, projectId)
  }
}

const openCreateAgent = async () => {
  agentDropdownOpen.value = false
  try {
    await loadAgentBackends()
    agentEditModalRef.value?.openCreate()
  } catch (error) {
    message.error(error.message || '打开新建智能体弹窗失败')
  }
}

const openAgentManagement = async () => {
  agentDropdownOpen.value = false
  if (!selectedAgentId.value) {
    message.warning('请先选择智能体')
    return
  }
  try {
    await loadAgentBackends()
    await agentEditModalRef.value?.openEdit(selectedAgentId.value)
  } catch (error) {
    message.error(error.message || '打开智能体配置失败')
  }
}
</script>

<style lang="less" scoped>
.agent-switch-empty {
  padding: 20px 8px;
  color: var(--gray-500);
  text-align: center;
  font-size: 13px;
}

.agent-view {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100vh;
  overflow: hidden;
}

.agent-view-body {
  --gap-radius: 6px;
  display: flex;
  flex-direction: row;
  width: 100%;
  flex: 1;
  height: 100%;
  overflow: hidden;
  position: relative;

  .content {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
}

.content {
  flex: 1;
  overflow: hidden;
}

.task-git-button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  padding: 0 10px;
  border: 1px solid var(--gray-200);
  border-radius: 8px;
  color: var(--gray-700);
  background: var(--gray-0);
  cursor: pointer;

  &:hover {
    border-color: var(--primary-400);
    color: var(--primary-600);
  }
}

@media (max-width: 640px) {
  .task-git-button span {
    display: none;
  }
}
</style>
