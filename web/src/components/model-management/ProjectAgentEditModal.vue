<script setup>
import { computed, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { Bot, RefreshCw, Settings2, SlidersHorizontal, Terminal, Upload, Wrench } from '@lucide/vue'

import { agentApi } from '@/apis/agent_api'
import { codingSandboxApi } from '@/apis/coding_sandbox_api'
import { projectAgentApi } from '@/apis/project_agent_api'
import { userApi } from '@/apis/user_api'
import AgentExecutionConfigForm from '@/components/AgentExecutionConfigForm.vue'
import ProjectAgentConfigForm from '@/components/model-management/ProjectAgentConfigForm.vue'
import FallbackAvatar from '@/components/common/FallbackAvatar.vue'
import { normalizeAgent } from '@/utils/agentConfigUtils'
import {
  buildExecutionConfigPatch,
  defaultCodingSettings,
  defaultSandboxPolicy,
  normalizeCodingSettings,
  normalizeSandboxPolicy
} from '@/utils/agentExecutionConfig'
import { generatePixelAvatar } from '@/utils/pixelAvatar'
import { MAX_IMAGE_UPLOAD_SIZE_BYTES, MAX_IMAGE_UPLOAD_SIZE_MB } from '@/utils/upload_limits'

const props = defineProps({
  open: { type: Boolean, default: false },
  agent: { type: Object, default: null },
  projectName: { type: String, default: '' }
})

const emit = defineEmits(['update:open', 'saved'])

const SECTION_ITEMS = [
  { key: 'basic', label: '基本信息', icon: Bot },
  { key: 'model', label: '模型配置', icon: SlidersHorizontal },
  { key: 'tools', label: '工具配置', icon: Wrench },
  { key: 'other', label: '其他配置', icon: Settings2 },
  { key: 'execution', label: '沙盒与编码', icon: Terminal }
]

const activeSection = ref('basic')
const saving = ref(false)
const iconUploading = ref(false)

const form = ref({ name: '', description: '', icon: '', slug: '', backend_id: '' })
let initialProfile = {}
const values = ref({})
let initialValues = {}
const baseValues = ref({})
const originalOverriddenKeys = ref([])
const resetFields = ref([])

const sandboxValues = ref(defaultSandboxPolicy())
const codingValues = ref(defaultCodingSettings())
const baseSandbox = ref(defaultSandboxPolicy())
const baseCoding = ref(defaultCodingSettings())
const sandboxOverridden = ref(false)
const codingOverridden = ref(false)
const resetSections = ref([])
const warmUpLoading = ref(false)
let initialSandbox = defaultSandboxPolicy()
let initialCoding = defaultCodingSettings()

const agentDetail = computed(() => (props.agent ? normalizeAgent(props.agent) : null))
const canManage = computed(() => !!agentDetail.value?.can_manage)
const configurableItems = computed(() => agentDetail.value?.configurable_items || {})
const previewDefaultIcon = computed(() =>
  agentDetail.value?.slug ? generatePixelAvatar(agentDetail.value.slug) : ''
)

const profileSnapshot = () => ({
  name: (form.value.name || '').trim(),
  description: (form.value.description || '').trim(),
  icon: (form.value.icon || '').trim()
})

const hasProfileChanges = computed(
  () => JSON.stringify(profileSnapshot()) !== JSON.stringify(initialProfile)
)

const hasConfigChanges = computed(() => {
  for (const [key, value] of Object.entries(values.value)) {
    if (JSON.stringify(value) !== JSON.stringify(initialValues[key])) return true
  }
  for (const key of Object.keys(initialValues)) {
    if (!(key in values.value)) return true
  }
  return false
})

const hasExecutionChanges = computed(
  () =>
    resetSections.value.length > 0 ||
    Object.keys(
      buildExecutionConfigPatch({
        initial: { sandbox: initialSandbox, coding: initialCoding },
        current: { sandbox: sandboxValues.value, coding: codingValues.value }
      })
    ).length > 0
)

const hasAnyChanges = computed(
  () =>
    hasProfileChanges.value ||
    hasConfigChanges.value ||
    resetFields.value.length > 0 ||
    hasExecutionChanges.value
)

const warmUpDisabled = computed(() => normalizeSandboxPolicy(sandboxValues.value).mode !== 'dedicated')

const closeModal = () => {
  if (saving.value || iconUploading.value) return
  emit('update:open', false)
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

const handleValuesUpdate = (nextValues) => {
  values.value = nextValues
  resetFields.value = resetFields.value.filter(
    (key) => JSON.stringify(nextValues[key]) === JSON.stringify(baseValues.value[key])
  )
}

const handleResetField = (key) => {
  const next = { ...values.value }
  if (Object.prototype.hasOwnProperty.call(baseValues.value, key)) {
    next[key] = baseValues.value[key]
  } else {
    delete next[key]
  }
  values.value = next
  if (!resetFields.value.includes(key)) {
    resetFields.value = [...resetFields.value, key]
  }
}

const handleSandboxUpdate = (value) => {
  sandboxValues.value = value
  if (JSON.stringify(normalizeSandboxPolicy(value)) !== JSON.stringify(baseSandbox.value)) {
    resetSections.value = resetSections.value.filter((field) => field !== 'sandbox')
  }
}

const handleCodingUpdate = (value) => {
  codingValues.value = value
  if (JSON.stringify(normalizeCodingSettings(value)) !== JSON.stringify(baseCoding.value)) {
    resetSections.value = resetSections.value.filter((field) => field !== 'coding')
  }
}

const restoreSandbox = () => {
  sandboxValues.value = { ...baseSandbox.value }
  if (!resetSections.value.includes('sandbox')) {
    resetSections.value = [...resetSections.value, 'sandbox']
  }
}

const restoreCoding = () => {
  codingValues.value = { ...baseCoding.value, executors: [...baseCoding.value.executors] }
  if (!resetSections.value.includes('coding')) {
    resetSections.value = [...resetSections.value, 'coding']
  }
}

const persistChanges = async () => {
  const agent = agentDetail.value
  if (!agent) return
  if (hasProfileChanges.value) {
    await agentApi.updateAgent(agent.slug, {
      name: form.value.name.trim(),
      description: form.value.description.trim() || null,
      icon: form.value.icon.trim() || null
    })
  }
  const reset = [...resetFields.value]
  const changed = {}
  for (const [key, value] of Object.entries(values.value)) {
    // 恢复继承的字段不写入覆盖，由 reset_fields 在后端删除旧覆盖。
    if (reset.includes(key)) continue
    if (JSON.stringify(value) !== JSON.stringify(initialValues[key])) {
      changed[key] = value
    }
  }
  const executionPatch = buildExecutionConfigPatch({
    initial: { sandbox: initialSandbox, coding: initialCoding },
    current: { sandbox: sandboxValues.value, coding: codingValues.value }
  })
  const changedSections = {}
  if (executionPatch.sandbox && !resetSections.value.includes('sandbox')) {
    changedSections.sandbox = executionPatch.sandbox
  }
  if (executionPatch.coding && !resetSections.value.includes('coding')) {
    changedSections.coding = executionPatch.coding
  }
  const resetAll = [...reset, ...resetSections.value]
  if (Object.keys(changed).length || Object.keys(changedSections).length || resetAll.length) {
    await projectAgentApi.updateOverrides(
      agent.project_id,
      agent.slug,
      { context: changed, ...changedSections },
      resetAll
    )
  }
  initialProfile = profileSnapshot()
  initialValues = JSON.parse(JSON.stringify(values.value))
  const appliedOverrides = new Set(originalOverriddenKeys.value)
  for (const key of reset) appliedOverrides.delete(key)
  for (const key of Object.keys(changed)) appliedOverrides.add(key)
  originalOverriddenKeys.value = [...appliedOverrides]
  resetFields.value = []
  if (resetSections.value.includes('sandbox')) {
    sandboxOverridden.value = false
  } else if (changedSections.sandbox) {
    sandboxOverridden.value = true
  }
  if (resetSections.value.includes('coding')) {
    codingOverridden.value = false
  } else if (changedSections.coding) {
    codingOverridden.value = true
  }
  initialSandbox = normalizeSandboxPolicy(sandboxValues.value)
  initialCoding = normalizeCodingSettings(codingValues.value)
  resetSections.value = []
}

const submit = async () => {
  const agent = agentDetail.value
  if (!agent) return
  if (!form.value.name.trim()) {
    message.error('请填写智能体名称')
    return
  }
  if (!canManage.value) {
    message.warning('当前智能体不可编辑')
    return
  }
  saving.value = true
  try {
    await persistChanges()
    emit('saved')
    emit('update:open', false)
    message.success('项目智能体已保存')
  } catch (error) {
    message.error(error.message || '保存项目智能体失败')
  } finally {
    saving.value = false
  }
}

const warmUp = async () => {
  const agent = agentDetail.value
  if (!agent || !canManage.value || warmUpDisabled.value) return
  warmUpLoading.value = true
  try {
    if (hasAnyChanges.value) {
      await persistChanges()
      emit('saved')
    }
    await codingSandboxApi.provision(agent.slug, agent.project_id)
    message.success('专属沙盒已按当前策略就绪')
  } catch (error) {
    message.error(error.message || '沙盒预热失败')
  } finally {
    warmUpLoading.value = false
  }
}

watch(
  () => props.open,
  (open) => {
    if (!open || !props.agent) return
    const agent = normalizeAgent(props.agent)
    form.value = {
      name: agent.name || '',
      description: agent.description || '',
      icon: agent.icon || '',
      slug: agent.slug || '',
      backend_id: agent.backend_id || ''
    }
    initialProfile = profileSnapshot()
    baseValues.value = { ...(agent.config_json?.context || {}) }
    const overrides = { ...(agent.config_overrides?.context || {}) }
    originalOverriddenKeys.value = Object.keys(overrides)
    const merged = { ...baseValues.value, ...overrides }
    values.value = JSON.parse(JSON.stringify(merged))
    initialValues = JSON.parse(JSON.stringify(merged))
    resetFields.value = []

    const baseExecutionSandbox = normalizeSandboxPolicy(agent.config_json?.sandbox)
    const baseExecutionCoding = normalizeCodingSettings(agent.config_json?.coding)
    const overrideSandbox = agent.config_overrides?.sandbox
    const overrideCoding = agent.config_overrides?.coding
    baseSandbox.value = baseExecutionSandbox
    baseCoding.value = baseExecutionCoding
    sandboxOverridden.value = !!overrideSandbox
    codingOverridden.value = !!overrideCoding
    const mergedSandbox = normalizeSandboxPolicy({ ...baseExecutionSandbox, ...(overrideSandbox || {}) })
    const mergedCoding = normalizeCodingSettings({
      executors: overrideCoding?.executors ?? baseExecutionCoding.executors,
      default_executor: overrideCoding?.default_executor ?? baseExecutionCoding.default_executor
    })
    sandboxValues.value = mergedSandbox
    codingValues.value = mergedCoding
    initialSandbox = JSON.parse(JSON.stringify(mergedSandbox))
    initialCoding = JSON.parse(JSON.stringify(mergedCoding))
    resetSections.value = []
    activeSection.value = 'basic'
  }
)
</script>

<template>
  <a-modal
    :open="open"
    class="agent-edit-modal"
    :width="820"
    :footer="null"
    :closable="false"
    @cancel="closeModal"
  >
    <template #title>
      <div class="agent-modal-titlebar">
        <span class="agent-modal-title">编辑项目智能体</span>
        <div class="agent-modal-actions">
          <a-button size="small" :disabled="saving" @click="closeModal">取消</a-button>
          <a-button
            size="small"
            type="primary"
            :loading="saving"
            :disabled="!hasAnyChanges || !canManage"
            @click="submit"
          >
            {{ hasAnyChanges ? '保存（有修改）' : '保存' }}
          </a-button>
        </div>
      </div>
    </template>

    <div class="agent-modal-content">
      <aside class="agent-modal-sidebar" aria-label="项目智能体配置分组">
        <button
          v-for="item in SECTION_ITEMS"
          :key="item.key"
          type="button"
          class="agent-modal-nav-item"
          :class="{ active: activeSection === item.key }"
          @click="activeSection = item.key"
        >
          <span class="nav-item-main">
            <component :is="item.icon" :size="16" />
            <span>{{ item.label }}</span>
          </span>
          <span
            v-if="
              item.key !== 'basic' &&
              (item.key === 'execution' ? hasExecutionChanges : hasConfigChanges)
            "
            class="nav-dirty-dot"
          />
        </button>
      </aside>

      <div class="agent-modal-main">
        <section v-show="activeSection === 'basic'" class="agent-modal-section">
          <a-alert
            v-if="!canManage"
            type="warning"
            show-icon
            message="当前智能体不可编辑：你不是它的创建者或管理员。"
            class="permission-alert"
          />

          <div class="agent-profile-header">
            <div class="agent-icon-preview" aria-label="智能体图标、名称与后端">
              <div class="agent-profile-main">
                <a-upload
                  :show-upload-list="false"
                  :before-upload="beforeIconUpload"
                  :disabled="iconUploading || !canManage"
                  accept="image/*"
                >
                  <div
                    class="agent-icon-upload"
                    :class="{ uploading: iconUploading, 'is-empty': !form.icon }"
                  >
                    <FallbackAvatar
                      v-if="form.icon || form.slug"
                      :src="form.icon"
                      :default-src="previewDefaultIcon"
                      :name="form.name || '智能体'"
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
                    v-model="form.name"
                    class="agent-inline-name-input"
                    type="text"
                    placeholder="点击输入智能体名称"
                    aria-label="智能体名称"
                    :disabled="!canManage"
                  />
                  <span class="agent-inline-slug">{{ form.slug }}</span>
                </div>
              </div>
              <div class="agent-backend-summary" aria-label="智能体后端">
                <span class="agent-backend-icon">
                  <Bot :size="16" />
                </span>
                <div class="agent-backend-text">
                  <span class="agent-backend-label">智能体后端</span>
                  <span class="agent-backend-name">{{ form.backend_id }}</span>
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
                :disabled="!canManage"
              />
            </label>
          </div>

          <div class="binding-block">
            <div class="section-heading">
              <span>项目归属</span>
            </div>
            <div class="binding-card">
              <div class="binding-row">
                <span class="binding-label">所属项目</span>
                <span class="binding-value">{{ projectName || agentDetail?.project_id }}</span>
              </div>
              <div class="binding-row">
                <span class="binding-label">智能体标识</span>
                <span class="binding-value">{{ agentDetail?.slug }}</span>
              </div>
              <div class="binding-row">
                <span class="binding-label">运行范围</span>
                <span class="binding-value">仅在该项目内可用，项目外会话无法选择或运行</span>
              </div>
            </div>
          </div>
        </section>

        <section
          v-show="activeSection !== 'basic' && activeSection !== 'execution'"
          class="agent-modal-section runtime-section"
        >
          <ProjectAgentConfigForm
            :segment="activeSection"
            :values="values"
            :configurable-items="configurableItems"
            :base-values="baseValues"
            :overridden-keys="originalOverriddenKeys"
            @update:values="handleValuesUpdate"
            @reset-field="handleResetField"
          />
        </section>

        <section v-show="activeSection === 'execution'" class="agent-modal-section">
          <AgentExecutionConfigForm
            :sandbox="sandboxValues"
            :coding="codingValues"
            :disabled="!canManage"
            :sandbox-overridden="sandboxOverridden"
            :coding-overridden="codingOverridden"
            :show-warm-up="true"
            :warm-up-loading="warmUpLoading"
            :warm-up-disabled="warmUpDisabled"
            @update:sandbox="handleSandboxUpdate"
            @update:coding="handleCodingUpdate"
            @reset-sandbox="restoreSandbox"
            @reset-coding="restoreCoding"
            @warm-up="warmUp"
          />
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
  grid-template-columns: 144px minmax(0, 1fr);
  height: min(72vh, 640px);
  min-height: 0;
  overflow: hidden;
  background: var(--gray-0);
}

.agent-modal-sidebar {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
  padding: 14px 10px;
  overflow-y: auto;
  border-right: 1px solid var(--gray-150);
  background: transparent;
}

.agent-modal-nav-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  min-height: 34px;
  padding: 6px 9px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: var(--gray-800);
  font-size: 13px;
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition:
    background 0.16s ease,
    border-color 0.16s ease,
    color 0.16s ease;

  &:hover {
    background: var(--gray-50);
    color: var(--gray-900);
  }

  &.active {
    background: var(--gray-100);
    color: var(--gray-900);

    span {
      font-weight: 600;
    }
  }
}

.nav-item-main {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  gap: 8px;

  svg {
    flex-shrink: 0;
    color: var(--gray-600);
  }
}

.nav-dirty-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--color-warning-600);
}

.agent-modal-main {
  min-width: 0;
  min-height: 0;
  overflow: hidden auto;
  overscroll-behavior: contain;
  padding: 22px 18px 24px 24px;
  scrollbar-gutter: stable;
  scrollbar-width: thin;
  scrollbar-color: var(--gray-300) transparent;

  &::-webkit-scrollbar {
    width: 6px;
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

.runtime-section {
  height: 100%;
}

.permission-alert {
  margin-bottom: 14px;
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

  &:hover:not(:disabled) {
    border-color: var(--gray-300);
    background: var(--gray-0);
  }

  &:focus {
    border-color: var(--main-300);
    background: var(--gray-0);
    box-shadow: 0 0 0 3px var(--main-50);
    outline: none;
  }

  &:disabled {
    color: var(--gray-700);
  }
}

.agent-inline-slug {
  width: 200px;
  max-width: 100%;
  padding: 1px 4px;
  overflow: hidden;
  color: var(--gray-500);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.agent-backend-name {
  max-width: 128px;
  overflow: hidden;
  color: var(--gray-900);
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
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

.binding-block {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--gray-150);
}

.binding-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  background: var(--gray-10);
}

.binding-row {
  display: flex;
  align-items: baseline;
  gap: 12px;
}

.binding-label {
  flex-shrink: 0;
  width: 72px;
  color: var(--gray-500);
  font-size: 12px;
}

.binding-value {
  min-width: 0;
  color: var(--gray-900);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
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
