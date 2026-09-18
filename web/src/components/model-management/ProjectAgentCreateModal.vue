<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { Bot, Copy, Microscope, RefreshCw, Upload } from '@lucide/vue'

import { agentApi } from '@/apis/agent_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import { userApi } from '@/apis/user_api'
import ProjectAgentConfigForm from '@/components/model-management/ProjectAgentConfigForm.vue'
import FallbackAvatar from '@/components/common/FallbackAvatar.vue'
import { useProjectsStore } from '@/stores/projects'
import { normalizeAgent } from '@/utils/agentConfigUtils'
import { generatePixelAvatar } from '@/utils/pixelAvatar'
import {
  DEFAULT_PROJECT_AGENT_NAME,
  buildCopiedProjectAgentDraft
} from '@/utils/projectAgentCopy'
import { MAX_IMAGE_UPLOAD_SIZE_BYTES, MAX_IMAGE_UPLOAD_SIZE_MB } from '@/utils/upload_limits'

const DEFAULT_AGENT_BACKEND_ID = 'ChatbotAgent'

const props = defineProps({
  open: { type: Boolean, default: false },
  projectId: { type: String, default: '' },
  backendOptions: { type: Array, default: () => [] }
})

const emit = defineEmits(['update:open', 'created'])

const projectsStore = useProjectsStore()

const nameInputRef = ref(null)
const submitting = ref(false)
const iconUploading = ref(false)
const schemaLoading = ref(false)
const copyLoading = ref(false)
const copySources = ref([])
const selectedCopyKey = ref('')

const form = ref({ slug: '', name: '', backend_id: DEFAULT_AGENT_BACKEND_ID, description: '', icon: '' })
const configValues = ref({})
const configurableItems = ref({})

const selectedBackendOption = computed(() =>
  props.backendOptions.find((backend) => backend.value === form.value.backend_id)
)
const selectedBackendLabel = computed(
  () => selectedBackendOption.value?.label || form.value.backend_id || '未选择'
)
const selectedBackendIcon = computed(() => {
  const backendText = `${form.value.backend_id} ${selectedBackendLabel.value}`.toLowerCase()
  return backendText.includes('deep') || backendText.includes('search') ? Microscope : Bot
})
const previewName = computed(() => form.value.name || '智能体')
const previewDefaultIcon = computed(() =>
  form.value.slug ? generatePixelAvatar(form.value.slug) : ''
)

const resetForm = () => {
  form.value = {
    slug: '',
    name: DEFAULT_PROJECT_AGENT_NAME,
    backend_id: props.backendOptions[0]?.value || DEFAULT_AGENT_BACKEND_ID,
    description: '',
    icon: ''
  }
  configValues.value = {}
  configurableItems.value = {}
  selectedCopyKey.value = ''
}

const loadBackendSchema = async () => {
  const backendId = form.value.backend_id
  if (!backendId) return
  schemaLoading.value = true
  try {
    const response = await agentApi.getAgentBackendDetail(backendId, {
      includeConfigurableItems: true
    })
    configurableItems.value = response.configurable_items || {}
  } catch (error) {
    message.error(error.message || '加载智能体配置项失败')
    configurableItems.value = {}
  } finally {
    schemaLoading.value = false
  }
}

const handleBackendChange = async () => {
  configValues.value = {}
  await loadBackendSchema()
}

const loadCopySources = async () => {
  copyLoading.value = true
  try {
    const sources = []
    const globalResponse = await agentApi.getAgents()
    for (const agent of globalResponse.agents || []) {
      const normalized = normalizeAgent(agent)
      if (normalized.is_builtin || normalized.is_default || !normalized.can_manage) continue
      sources.push({
        key: `${normalized.slug}::`,
        slug: normalized.slug,
        project_id: null,
        project_name: '',
        name: normalized.name,
        backend_id: normalized.backend_id,
        description: normalized.description || '',
        icon: normalized.icon || '',
        configurable_items: null,
        effective_context: null
      })
    }
    await projectsStore.loadProjects()
    for (const project of projectsStore.projects || []) {
      try {
        const response = await projectAgentApi.list(project.id)
        for (const agent of response.agents || []) {
          const normalized = normalizeAgent(agent)
          if (normalized.is_builtin || normalized.is_default || !normalized.can_manage) continue
          sources.push({
            key: `${normalized.slug}::${project.id}`,
            slug: normalized.slug,
            project_id: project.id,
            project_name: project.name || project.id,
            name: normalized.name,
            backend_id: normalized.backend_id,
            description: normalized.description || '',
            icon: normalized.icon || '',
            configurable_items: normalized.configurable_items || {},
            effective_context: normalized.effective_context || {}
          })
        }
      } catch {
        // 单个项目读取失败不阻塞其它复制来源
      }
    }
    copySources.value = sources
  } catch (error) {
    message.error(error.message || '加载可复制智能体失败')
    copySources.value = []
  } finally {
    copyLoading.value = false
  }
}

const copySourceOptions = computed(() =>
  copySources.value.map((source) => ({
    value: source.key,
    label: source.project_id ? `${source.name}（${source.project_name}）` : `${source.name}（全局）`
  }))
)

const applyCopy = async () => {
  const source = copySources.value.find((item) => item.key === selectedCopyKey.value)
  if (!source) {
    message.warning('请先选择要复制的智能体')
    return
  }
  try {
    let configurableItemsForSource = source.configurable_items
    let contextForSource = source.effective_context
    if (!configurableItemsForSource || !contextForSource) {
      const detailResponse = await agentApi.getAgentDetail(source.slug)
      const detail = normalizeAgent(detailResponse.agent || detailResponse)
      configurableItemsForSource = detail.configurable_items || {}
      contextForSource = detail.config_json?.context || {}
    }
    const draft = buildCopiedProjectAgentDraft(
      { ...source, context: contextForSource },
      form.value
    )
    form.value = {
      ...form.value,
      backend_id: draft.backend_id,
      description: draft.description,
      icon: draft.icon,
      name: draft.name
    }
    configurableItems.value = configurableItemsForSource
    configValues.value = draft.configValues
    message.success(`已复制「${source.name}」的配置，确认后可创建`)
  } catch (error) {
    message.error(error.message || '复制智能体配置失败')
  }
}

const beforeIconUpload = (file) => {
  if (!file.type.startsWith('image/')) {
    message.error('只能上传图片文件')
    return false
  }
  if (file.size > MAX_IMAGE_UPLOAD_SIZE_BYTES) {
    message.error(`图片大小不能超过 ${MAX_IMAGE_UPLOAD_SIZE_MB}MB`)
    return false
  }
  uploadIcon(file)
  return false
}

const uploadIcon = async (file) => {
  iconUploading.value = true
  try {
    const data = await userApi.uploadImage(file)
    form.value.icon = data.image_url || data.url || ''
    message.success('图标上传成功')
  } catch (error) {
    message.error(error.message || '图标上传失败')
  } finally {
    iconUploading.value = false
  }
}

const focusNameInput = async () => {
  await nextTick()
  const el = nameInputRef.value
  el?.focus?.()
  el?.select?.()
}

const closeModal = () => {
  if (submitting.value || iconUploading.value) return
  emit('update:open', false)
}

const submit = async () => {
  const name = form.value.name.trim()
  if (!name) {
    message.error('请填写智能体名称')
    return
  }
  submitting.value = true
  try {
    await projectAgentApi.create(props.projectId, {
      name,
      slug: form.value.slug.trim() || null,
      backend_id: form.value.backend_id,
      description: form.value.description.trim() || null,
      icon: form.value.icon.trim() || null,
      config_json: { context: { ...configValues.value } }
    })
    emit('created')
    emit('update:open', false)
  } catch (error) {
    message.error(error.message || '创建项目智能体失败')
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.open,
  async (open) => {
    if (!open) return
    resetForm()
    await loadBackendSchema()
    await loadCopySources()
    focusNameInput()
  }
)
</script>

<template>
  <a-modal
    :open="open"
    class="agent-edit-modal"
    :width="740"
    :footer="null"
    :closable="false"
    @cancel="closeModal"
  >
    <template #title>
      <div class="agent-modal-titlebar">
        <span class="agent-modal-title">新建项目智能体</span>
        <div class="agent-modal-actions">
          <a-button size="small" :disabled="submitting" @click="closeModal">取消</a-button>
          <a-button size="small" type="primary" :loading="submitting" @click="submit">创建</a-button>
        </div>
      </div>
    </template>

    <div class="agent-modal-content without-sidebar create-mode">
      <div class="agent-modal-main">
        <section class="agent-modal-section">
          <div class="copy-block">
            <div class="section-heading">
              <Copy :size="14" />
              <span>复制已有智能体配置</span>
            </div>
            <div class="copy-row">
              <a-select
                v-model:value="selectedCopyKey"
                :options="copySourceOptions"
                :loading="copyLoading"
                show-search
                option-filter-prop="label"
                allow-clear
                placeholder="选择一个已有智能体，复制其参数后继续编辑"
                class="copy-select"
              />
              <a-button :disabled="!selectedCopyKey" @click="applyCopy">复制配置</a-button>
            </div>
            <p class="copy-hint">只填入当前草稿，方便修改；点击“创建”前不会提交任何内容。</p>
          </div>

          <div class="agent-profile-header">
            <div class="agent-icon-preview" aria-label="智能体图标、名称与后端">
              <div class="agent-profile-main">
                <a-upload
                  :show-upload-list="false"
                  :before-upload="beforeIconUpload"
                  :disabled="iconUploading"
                  accept="image/*"
                >
                  <div
                    class="agent-icon-upload"
                    :class="{ uploading: iconUploading, 'is-empty': !form.icon }"
                  >
                    <FallbackAvatar
                      v-if="form.icon"
                      :src="form.icon"
                      :default-src="previewDefaultIcon"
                      :name="previewName"
                      :seed="form.slug || form.name"
                      kind="agent"
                      :size="56"
                      shape="rounded"
                      :alt="`${form.name || '智能体'}图标`"
                      class="agent-icon-preview-avatar"
                    />
                    <div class="agent-icon-mask">
                      <RefreshCw v-if="iconUploading" :size="16" class="spinning" />
                      <Upload v-else :size="16" />
                      <span>{{ form.icon ? '更换图标' : '上传图标' }}</span>
                    </div>
                  </div>
                </a-upload>
                <div class="agent-icon-preview-text">
                  <input
                    ref="nameInputRef"
                    v-model="form.name"
                    class="agent-inline-name-input"
                    type="text"
                    placeholder="点击输入智能体名称"
                    aria-label="智能体名称"
                  />
                  <input
                    v-model="form.slug"
                    class="agent-inline-slug-input"
                    type="text"
                    placeholder="标识可选，留空自动生成"
                    aria-label="智能体标识"
                  />
                </div>
              </div>
              <div class="agent-backend-summary editable" aria-label="智能体后端">
                <span class="agent-backend-icon">
                  <component :is="selectedBackendIcon" :size="16" />
                </span>
                <div class="agent-backend-text">
                  <span class="agent-backend-label">智能体后端</span>
                  <a-select
                    v-model:value="form.backend_id"
                    class="agent-backend-select"
                    :bordered="false"
                    :options="backendOptions"
                    @change="handleBackendChange"
                  />
                </div>
              </div>
            </div>
          </div>

          <div class="modal-form">
            <label class="form-label full-width">
              <span>描述</span>
              <a-textarea
                v-model:value="form.description"
                class="agent-description-textarea"
                :rows="3"
                placeholder="可选"
              />
            </label>
          </div>

          <div class="runtime-config-block">
            <div class="section-heading">
              <span>运行配置</span>
            </div>
            <a-spin :spinning="schemaLoading">
              <ProjectAgentConfigForm
                :values="configValues"
                :configurable-items="configurableItems"
                @update:values="(values) => (configValues = values)"
              />
            </a-spin>
          </div>
        </section>
      </div>
    </div>
  </a-modal>
</template>

<style lang="less" scoped>
.agent-modal-titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
}

.agent-modal-title {
  color: var(--gray-900);
  font-size: 16px;
  font-weight: 600;
}

.agent-modal-actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;

  :deep(.ant-btn) {
    min-width: 56px;
    border-radius: 6px;
    font-weight: 500;
  }

  :deep(.ant-btn-primary) {
    border-color: var(--main-700);
    background: var(--main-700);

    &:hover,
    &:focus {
      border-color: var(--main-800);
      background: var(--main-800);
    }
  }
}

.agent-modal-content {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  height: auto;
  min-height: 360px;
  overflow: hidden;
  background: var(--gray-0);
}

.agent-modal-main {
  min-width: 0;
  min-height: 0;
  max-height: min(72vh, 640px);
  overflow: hidden auto;
  overscroll-behavior: contain;
  padding: 22px 18px 24px 24px;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: var(--gray-300) transparent;

  &::-webkit-scrollbar {
    width: 6px;
  }

  &::-webkit-scrollbar-track {
    background: transparent;
  }

  &::-webkit-scrollbar-thumb {
    border: 2px solid transparent;
    border-radius: 999px;
    background: var(--gray-300);
    background-clip: content-box;
  }
}

.agent-modal-section {
  min-height: 0;
  background: var(--gray-0);
}

.copy-block {
  margin-bottom: 18px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--gray-150);
}

.copy-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.copy-select {
  flex: 1;
  min-width: 0;
}

.copy-hint {
  margin: 8px 0 0;
  color: var(--gray-500);
  font-size: 12px;
}

.section-heading {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 12px;
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
}

.agent-profile-header {
  margin-bottom: 16px;
}

.agent-icon-preview {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-width: 0;
  gap: 16px;

  :deep(.ant-upload) {
    display: block;
  }
}

.agent-profile-main {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 10px;
}

.agent-icon-upload {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  overflow: hidden;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--main-30);
  cursor: pointer;
  transition:
    border-color 0.16s ease,
    box-shadow 0.16s ease;

  .agent-icon-preview-avatar {
    width: 100%;
    height: 100%;
    border: 0;
  }

  &:hover,
  &:focus-within,
  &.uploading {
    border-color: var(--main-300);
    box-shadow: 0 0 0 3px var(--main-50);
  }

  &:hover .agent-icon-mask,
  &:focus-within .agent-icon-mask,
  &.uploading .agent-icon-mask,
  &.is-empty .agent-icon-mask {
    opacity: 1;
  }

  &.is-empty {
    border-style: dashed;
    background: var(--gray-0);
  }
}

.agent-icon-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  background: color-mix(in srgb, var(--gray-900) 62%, transparent);
  color: var(--gray-0);
  font-size: 11px;
  font-weight: 600;
  opacity: 0;
  transition: opacity 0.16s ease;
}

.agent-icon-upload.is-empty .agent-icon-mask {
  background: transparent;
  color: var(--gray-600);
}

.agent-icon-preview-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: 4px;
  line-height: 1.25;
}

.agent-inline-name-input {
  width: 200px;
  max-width: 100%;
  padding: 1px 4px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--gray-900);
  caret-color: var(--main-700);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  transition:
    border-color 0.16s ease,
    background 0.16s ease,
    box-shadow 0.16s ease;

  &::placeholder {
    color: var(--gray-400);
  }

  &:hover {
    border-color: var(--gray-300);
    background: var(--gray-0);
  }

  &:focus {
    border-color: var(--main-300);
    background: var(--gray-0);
    box-shadow: 0 0 0 3px var(--main-50);
    outline: none;
  }
}

.agent-inline-slug-input {
  width: 200px;
  max-width: 100%;
  padding: 1px 4px;
  overflow: hidden;
  border: 1px solid transparent;
  border-radius: 2px;
  background: transparent;
  color: var(--gray-500);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;

  &::placeholder {
    color: var(--gray-400);
  }

  &:hover,
  &:focus {
    border-color: var(--gray-300);
    background: var(--gray-0);
    outline: none;
  }
}

.agent-backend-summary {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  gap: 10px;
  width: 190px;
  min-height: 56px;
  padding: 10px 12px;
  border: 1px solid var(--gray-200);
  border-radius: 12px;
  background: var(--gray-10);
  color: var(--gray-700);

  &.editable {
    padding-right: 8px;
  }
}

.agent-backend-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--gray-100);
  color: var(--gray-700);
}

.agent-backend-text {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
  gap: 3px;
  line-height: 1.2;
}

.agent-backend-label {
  color: var(--gray-500);
  font-size: 11px;
}

.agent-backend-select {
  width: 128px;
  margin: -3px 0 -5px -11px;

  :deep(.ant-select-selector) {
    background: transparent !important;
    box-shadow: none !important;
  }

  :deep(.ant-select-selection-item) {
    color: var(--gray-900);
    font-size: 13px;
    font-weight: 600;
  }

  :deep(.ant-select-arrow) {
    color: var(--gray-500);
  }
}

.modal-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-label {
  display: flex;
  flex-direction: column;
  gap: 6px;

  > span {
    color: var(--gray-700);
    font-size: 12px;
    font-weight: 500;
  }
}

.agent-description-textarea {
  min-height: 80px;
  padding: 10px 12px;
  border-color: var(--gray-200);
  border-radius: 8px;
  background: var(--gray-10);
  color: var(--gray-900);
  font-size: 13px;
  line-height: 1.6;
  resize: vertical;

  &::placeholder {
    color: var(--gray-400);
  }

  &:hover {
    border-color: var(--gray-300);
    background: var(--gray-0);
  }

  &:focus {
    border-color: var(--main-300);
    background: var(--gray-0);
    box-shadow: 0 0 0 3px var(--main-50);
  }
}

.full-width {
  grid-column: 1 / -1;
}

.runtime-config-block {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--gray-150);
}

.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

:global(.agent-edit-modal .ant-modal-content) {
  overflow: hidden;
  padding: 0;
  border-radius: 12px;
}

:global(.agent-edit-modal .ant-modal-header) {
  margin: 0;
  padding: 18px 24px;
  border-bottom: 1px solid var(--gray-150);
  background: var(--gray-0);
}

:global(.agent-edit-modal .ant-modal-title) {
  width: 100%;
}

:global(.agent-edit-modal .ant-modal-body) {
  padding: 0;
}
</style>
