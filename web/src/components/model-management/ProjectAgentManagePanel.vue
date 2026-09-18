<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { message, Modal } from 'ant-design-vue'
import { Bot, Plus, RefreshCw, SquarePen, Link2, Unlink } from '@lucide/vue'

import { agentApi } from '@/apis/agent_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import ProjectAgentCreateModal from '@/components/model-management/ProjectAgentCreateModal.vue'
import ProjectAgentEditModal from '@/components/model-management/ProjectAgentEditModal.vue'
import PageShoulder from '@/components/shared/PageShoulder.vue'
import InfoCard from '@/components/shared/InfoCard.vue'
import ExtensionCardGrid from '@/components/extensions/ExtensionCardGrid.vue'
import FallbackAvatar from '@/components/common/FallbackAvatar.vue'
import { useProjectsStore } from '@/stores/projects'
import { normalizeAgent, normalizeAgentBackendOption } from '@/utils/agentConfigUtils'
import { generatePixelAvatar } from '@/utils/pixelAvatar'

const projectsStore = useProjectsStore()

const selectedProjectId = ref('')
const managedAgents = ref([])
const agentLoading = ref(false)
const submitting = ref(false)
const errorText = ref('')
const searchQuery = ref('')
const projectSelectRef = ref(null)
const projectSelectShaking = ref(false)

const createOpen = ref(false)
const bindOpen = ref(false)
const editOpen = ref(false)

const backendOptions = ref([])

const bindCandidates = ref([])
const bindLoading = ref(false)

const editAgent = ref(null)

const projectOptions = computed(() => [
  { value: '', label: '全部项目' },
  ...(projectsStore.projects || []).map((project) => ({
    value: project.id,
    label: project.name || project.id
  }))
])

const currentProject = computed(() =>
  (projectsStore.projects || []).find((project) => project.id === selectedProjectId.value)
)

const filteredAgents = computed(() => {
  const keyword = searchQuery.value.trim().toLowerCase()
  if (!keyword) return managedAgents.value
  return managedAgents.value.filter(
    (agent) =>
      String(agent.name || '').toLowerCase().includes(keyword) ||
      String(agent.slug || '').toLowerCase().includes(keyword)
  )
})

const overriddenCount = (agent) => Object.keys(agent?.config_overrides?.context || {}).length

const loadProjects = async () => {
  try {
    const projects = await projectsStore.loadProjects()
    if (
      selectedProjectId.value &&
      !projects.some((project) => project.id === selectedProjectId.value)
    ) {
      selectedProjectId.value = ''
    }
  } catch (error) {
    errorText.value = error.message || '项目加载失败'
  }
}

const loadAgents = async () => {
  agentLoading.value = true
  errorText.value = ''
  try {
    if (selectedProjectId.value) {
      const project = currentProject.value
      const response = await projectAgentApi.list(selectedProjectId.value)
      managedAgents.value = (response.agents || []).map((agent) => ({
        ...normalizeAgent(agent),
        project_id: selectedProjectId.value,
        project_name: project?.name || selectedProjectId.value
      }))
    } else {
      const projects = projectsStore.projects || []
      const groups = await Promise.all(
        projects.map(async (project) => {
          const response = await projectAgentApi.list(project.id)
          return (response.agents || []).map((agent) => ({
            ...normalizeAgent(agent),
            project_id: project.id,
            project_name: project.name || project.id
          }))
        })
      )
      managedAgents.value = groups.flat()
    }
  } catch (error) {
    errorText.value = error.message || '项目智能体加载失败'
  } finally {
    agentLoading.value = false
  }
}

const loadBackendOptions = async () => {
  try {
    const response = await agentApi.getAgentBackends()
    backendOptions.value = (response.backends || []).map(normalizeAgentBackendOption)
  } catch (error) {
    message.error(error.message || '加载智能体后端失败')
  }
}

const requireSelectedProject = () => {
  if (selectedProjectId.value) return true
  message.warning('请先在左上角选择要操作的项目')
  projectSelectShaking.value = false
  requestAnimationFrame(() => {
    projectSelectShaking.value = true
  })
  setTimeout(() => {
    projectSelectShaking.value = false
  }, 600)
  projectSelectRef.value?.focus?.()
  return false
}

const openCreateModal = () => {
  if (!requireSelectedProject()) return
  createOpen.value = true
}

const handleCreated = async () => {
  await loadAgents()
  message.success('项目智能体已创建')
}

const openBindModal = async () => {
  if (!requireSelectedProject()) return
  bindOpen.value = true
  bindLoading.value = true
  try {
    const response = await agentApi.getAgents()
    bindCandidates.value = (response.agents || [])
      .map(normalizeAgent)
      .filter(
        (agent) =>
          !agent.is_subagent &&
          !agent.is_default &&
          !agent.is_builtin &&
          agent.can_manage
      )
  } catch (error) {
    message.error(error.message || '加载可绑定智能体失败')
    bindCandidates.value = []
  } finally {
    bindLoading.value = false
  }
}

const bindAgent = async (agent) => {
  submitting.value = true
  try {
    await projectAgentApi.bind(selectedProjectId.value, agent.slug || agent.id)
    bindOpen.value = false
    await loadAgents()
    message.success('已绑定为项目数字员工')
  } catch (error) {
    message.error(error.message || '绑定失败')
  } finally {
    submitting.value = false
  }
}

const openEditModal = (agent) => {
  editAgent.value = agent
  editOpen.value = true
}

const handleEditSaved = async () => {
  await loadAgents()
}

const unbindAgent = (agent, { deleteAgent = false } = {}) => {
  Modal.confirm({
    title: deleteAgent ? `解绑并删除 ${agent.name}` : `解绑 ${agent.name}`,
    content: deleteAgent
      ? '解绑后该智能体不再属于任何项目，将从你的个人智能体中删除，且不可恢复。'
      : '解绑后该智能体不再受项目范围限制，将回到你的个人智能体列表。',
    okText: deleteAgent ? '解绑并删除' : '解绑',
    okType: deleteAgent ? 'danger' : 'primary',
    cancelText: '取消',
    async onOk() {
      try {
        await projectAgentApi.unbind(agent.project_id || selectedProjectId.value, agent.slug, {
          deleteAgent
        })
        await loadAgents()
        message.success(deleteAgent ? '已解绑并删除' : '已解绑')
      } catch (error) {
        message.error(error.message || '解绑失败')
      }
    }
  })
}

const refresh = async () => {
  await loadAgents()
}

watch(selectedProjectId, () => {
  loadAgents()
})

onMounted(async () => {
  await Promise.all([loadProjects(), loadBackendOptions()])
  await loadAgents()
})

defineExpose({
  loading: agentLoading,
  refresh
})
</script>

<template>
  <div class="project-agent-manage-panel">
    <PageShoulder v-model:search="searchQuery" search-placeholder="搜索项目数字员工...">
      <template #actions>
        <div class="project-select-wrap" :class="{ 'is-shaking': projectSelectShaking }">
          <a-select
            ref="projectSelectRef"
            v-model:value="selectedProjectId"
            :options="projectOptions"
            :loading="projectsStore.isLoading"
            placeholder="全部项目"
            class="project-select"
          />
        </div>
        <a-button type="primary" class="lucide-icon-btn" @click="openCreateModal">
          <Plus :size="14" />
          新建项目智能体
        </a-button>
        <a-button class="lucide-icon-btn" @click="openBindModal">
          <Link2 :size="14" />
          绑定已有智能体
        </a-button>
        <a-button class="lucide-icon-btn" :loading="agentLoading" @click="refresh">
          <RefreshCw :size="14" />
        </a-button>
      </template>
    </PageShoulder>

    <div v-if="errorText" class="panel-error">{{ errorText }}</div>

    <div v-if="agentLoading" class="agent-empty-state">
      <a-spin />
    </div>
    <div v-else-if="!managedAgents.length" class="agent-empty-state">
      <a-empty
        :description="
          !(projectsStore.projects || []).length
            ? '还没有可管理的项目，请先在工作台创建项目'
            : selectedProjectId
              ? '该项目还没有数字员工，点击右上角创建或绑定'
              : '还没有项目数字员工，选择项目后可创建或绑定'
        "
      />
    </div>
    <div v-else-if="!filteredAgents.length" class="agent-empty-state">
      <a-empty :image="false" description="没有匹配的项目数字员工" />
    </div>

    <template v-else>
      <section class="agent-group-section">
        <div class="agent-group-header">
          <span>{{ currentProject?.name || '全部项目' }} · {{ filteredAgents.length }} 个数字员工</span>
        </div>
        <ExtensionCardGrid :min-width="320">
          <InfoCard
            v-for="agent in filteredAgents"
            :key="`${agent.project_id}::${agent.slug}`"
            :title="agent.name"
            :subtitle="agent.slug"
            :description="agent.description || '暂无描述'"
            :default-icon="Bot"
            :tags="[
              ...(agent.project_name ? [{ name: agent.project_name, color: 'gray' }] : []),
              {
                name: overriddenCount(agent) ? `覆盖 ${overriddenCount(agent)} 项` : '继承基础配置',
                color: overriddenCount(agent) ? 'blue' : 'gray'
              },
              ...(agent.is_subagent ? [{ name: '子智能体', color: 'gray' }] : [])
            ]"
            class="config-card agent-card"
          >
            <template #icon>
              <FallbackAvatar
                class="agent-card-icon-image"
                :src="agent.icon"
                :default-src="agent.id ? generatePixelAvatar(agent.id) : ''"
                :name="agent.name || agent.slug"
                :seed="agent.slug"
                kind="agent"
                :size="40"
                shape="rounded"
                :alt="`${agent.name || '智能体'}图标`"
              />
            </template>

            <template #card-more-action-corner>
              <a-menu>
                <a-menu-item key="edit" @click.stop="openEditModal(agent)">
                  <span class="lucide-menu-item">
                    <SquarePen :size="14" />
                    <span>编辑项目配置</span>
                  </span>
                </a-menu-item>
                <a-menu-item key="unbind" @click.stop="unbindAgent(agent)">
                  <span class="lucide-menu-item">
                    <Unlink :size="14" />
                    <span>解绑</span>
                  </span>
                </a-menu-item>
                <a-menu-item key="unbind-delete" danger @click.stop="unbindAgent(agent, { deleteAgent: true })">
                  <span class="lucide-menu-item">
                    <Unlink :size="14" />
                    <span>解绑并删除</span>
                  </span>
                </a-menu-item>
              </a-menu>
            </template>
          </InfoCard>
        </ExtensionCardGrid>
      </section>
    </template>

    <ProjectAgentCreateModal
      v-model:open="createOpen"
      :project-id="selectedProjectId"
      :backend-options="backendOptions"
      @created="handleCreated"
    />

    <a-modal
      v-model:open="bindOpen"
      title="绑定已有智能体"
      :footer="null"
      width="560px"
    >
      <a-spin :spinning="bindLoading">
        <a-empty v-if="!bindCandidates.length" description="没有可绑定的智能体（绑定后该智能体将只能在当前项目内使用）" />
        <div v-else class="bind-list">
          <div v-for="agent in bindCandidates" :key="agent.slug" class="bind-item">
            <span class="bind-item-name">{{ agent.name }}</span>
            <span class="bind-item-slug">{{ agent.slug }}</span>
            <a-button size="small" type="primary" :loading="submitting" @click="bindAgent(agent)">
              绑定
            </a-button>
          </div>
          <p class="bind-hint">绑定后该智能体成为项目数字员工，只能在当前项目内使用。</p>
        </div>
      </a-spin>
    </a-modal>

    <ProjectAgentEditModal
      v-model:open="editOpen"
      :agent="editAgent"
      :project-name="editAgent?.project_name || currentProject?.name || ''"
      @saved="handleEditSaved"
    />
  </div>
</template>

<style lang="less" scoped>
.project-agent-manage-panel {
  height: 100%;
  min-height: 0;
  padding-bottom: var(--page-padding);
}

.project-select {
  min-width: 200px;
}

.panel-error {
  margin: 12px var(--page-padding) 0;
  color: var(--color-error-600, #cf1322);
  font-size: 13px;
}

.agent-empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 100px 20px;
  text-align: center;
}

.agent-group-section + .agent-group-section {
  padding-top: 2px;
}

.agent-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px var(--page-padding) 0;
  color: var(--gray-500);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.4px;
  line-height: 18px;
}

.agent-card-icon-image {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
}

.agent-card :deep(.info-card-tags) {
  justify-content: flex-start;
  margin-top: auto;
}

.bind-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.bind-item {
  display: grid;
  grid-template-columns: 1fr auto auto;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--gray-100);
  border-radius: 8px;
}

.bind-item-name {
  color: var(--gray-1000);
  font-weight: 500;
}

.bind-item-slug {
  color: var(--gray-500);
  font-size: 12px;
}

.bind-hint {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}

.project-select-wrap {
  display: inline-flex;
  border-radius: 8px;

  &.is-shaking {
    animation: project-select-shake 0.5s ease;
    box-shadow: 0 0 0 3px var(--color-warning-50);
  }
}

@keyframes project-select-shake {
  0%,
  100% {
    transform: translateX(0);
  }
  20% {
    transform: translateX(-5px);
  }
  40% {
    transform: translateX(5px);
  }
  60% {
    transform: translateX(-3px);
  }
  80% {
    transform: translateX(3px);
  }
}
</style>
