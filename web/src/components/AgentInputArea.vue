<template>
  <div class="agent-composer" :class="{ 'has-extra': showExtra && $slots.extra }">
    <div v-if="showExtra && $slots.extra" class="composer-extra-region" aria-label="对话上下文">
      <slot name="extra"></slot>
    </div>

    <MessageInputComponent
      ref="inputRef"
      :model-value="modelValue"
      @update:modelValue="updateValue"
      :is-loading="isLoading"
      :disabled="disabled"
      :send-button-disabled="sendButtonDisabled || sendLocked"
      :placeholder="placeholder"
      :mention="mention"
      :thread-id="threadId"
      :file-upload-enabled="supportsFileUpload"
      :show-options-left="showInputOptions"
      :enter-to-newline="sendLocked"
      @send="handleSend"
      @keydown="handleKeyDown"
      @composition-change="handleCompositionChange"
      @paste-image="handlePastedImage"
      @drop-files="handleDroppedFiles"
    >
      <template #top>
        <div v-if="currentImage || previewAttachments.length" class="input-top-stack">
          <ImagePreviewComponent
            v-if="currentImage"
            :image-data="currentImage"
            @remove="handleImageRemoved"
            class="image-preview-wrapper"
          />

          <div v-if="previewAttachments.length" class="attachment-preview-list">
            <div
              v-for="attachment in previewAttachments"
              :key="attachment.fileId"
              class="attachment-file-card"
            >
              <div class="attachment-file-icon">
                <FileTypeIcon :name="attachment.name" :size="18" />
              </div>
              <div class="attachment-file-body">
                <div class="attachment-file-name" :title="attachment.name">
                  {{ attachment.name }}
                </div>
                <div class="attachment-file-meta">{{ attachment.meta }}</div>
              </div>
              <button
                class="attachment-remove-btn"
                type="button"
                :aria-label="`移除附件 ${attachment.name}`"
                @click.stop="handleAttachmentRemoved(attachment)"
              >
                <X :size="14" />
              </button>
            </div>
          </div>
        </div>
      </template>
      <template #options-left>
        <AttachmentOptionsComponent
          :disabled="disabled"
          :file-upload-enabled="supportsFileUpload"
          :project-file-pick-enabled="supportsProjectFilePick"
          :mention="mention"
          @upload="handleAttachmentUpload"
          @upload-image="handleImageUpload"
          @upload-image-success="handleImageUploadSuccess"
          @select-mention="handleMentionSelect"
          @select-project-file="handleProjectFileSelect"
        />
      </template>
      <template #actions-left>
        <div class="input-actions-left">
          <slot name="actions-left-extra"></slot>
        </div>
      </template>
      <template #actions-right>
        <div class="input-actions-right">
          <slot name="actions-right-extra"></slot>
        </div>
      </template>
      <template #before-send>
        <button
          type="button"
          class="input-action-btn send-lock-btn"
          :class="{ active: sendLocked }"
          :title="sendLocked ? '已锁定发送（Cmd/Ctrl+L 解锁）' : '锁定发送（Cmd/Ctrl+L）'"
          :aria-pressed="sendLocked"
          aria-label="锁定发送"
          @click="toggleSendLock"
        >
          <component :is="sendLocked ? Lock : LockOpen" :size="16" />
        </button>
      </template>
    </MessageInputComponent>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import MessageInputComponent from '@/components/MessageInputComponent.vue'
import ImagePreviewComponent from '@/components/ImagePreviewComponent.vue'
import AttachmentOptionsComponent from '@/components/AttachmentOptionsComponent.vue'
import { Lock, LockOpen, X } from '@lucide/vue'
import { normalizeAttachmentPreviews } from '@/utils/file_utils'
import { uploadMultimodalImage } from '@/utils/multimodal_image_upload'
import { readSendLockPreference, writeSendLockPreference } from '@/utils/sendLock'
import FileTypeIcon from '@/components/common/FileTypeIcon.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  isLoading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  sendButtonDisabled: { type: Boolean, default: false },
  mention: { type: Object, default: () => null },
  threadId: { type: String, default: '' },
  showExtra: { type: Boolean, default: false },
  supportsFileUpload: { type: Boolean, default: false },
  supportsProjectFilePick: { type: Boolean, default: false },
  attachments: {
    type: Array,
    default: () => []
  }
})

const emit = defineEmits([
  'update:modelValue',
  'send',
  'keydown',
  'upload-attachment',
  'remove-attachment',
  'select-project-file'
])

const inputRef = ref(null)
const currentImage = ref(null)
// 输入法组合态：中文输入法确认候选词时会派发 key 为 Enter 但 keyCode 为 229 的回车，
// 需要与真正的发送回车区分，避免误提交。
const isComposing = ref(false)
// 发送锁：长文本编辑时手动锁定，锁定期间回车与发送按钮均被拦截，编辑完成后手动解锁。
const sendLocked = ref(readSendLockPreference())
const placeholder = '问点什么？使用 @ 可以选择文件、知识库或技能进行引用。'

const previewAttachments = computed(() => normalizeAttachmentPreviews(props.attachments))
const showInputOptions = computed(
  () =>
    props.supportsFileUpload ||
    Boolean(props.mention?.knowledgeBases?.length) ||
    Boolean(props.mention?.skills?.length)
)

const updateValue = (val) => {
  emit('update:modelValue', val)
}

const handleAttachmentUpload = (files = []) => {
  emit('upload-attachment', files)
}

const handleImageUpload = (imageData) => {
  if (imageData && imageData.success) {
    currentImage.value = imageData
  }
}

const handlePastedImage = async (file) => {
  if (props.disabled || !props.supportsFileUpload) return

  try {
    const imageData = await uploadMultimodalImage(file)
    handleImageUpload(imageData)
  } catch (error) {
    console.error('图片上传失败:', error)
  }
}

const handleDroppedFiles = (files = []) => {
  if (props.disabled || !props.supportsFileUpload || !files.length) return
  handleAttachmentUpload(files)
}

const handleImageUploadSuccess = () => {
  if (inputRef.value) {
    inputRef.value.closeOptions()
  }
}

const handleMentionSelect = (item) => {
  inputRef.value?.insertMention(item)
  inputRef.value?.closeOptions()
}

const handleProjectFileSelect = () => {
  emit('select-project-file')
}

const handleImageRemoved = () => {
  currentImage.value = null
}

// 发送被后端拒绝时把旧图片恢复到输入区，覆盖等待期间可能新选的图片，
// 避免旧图片被悄悄丢弃；用户可重新选择新图片。
const restoreImage = (image) => {
  currentImage.value = image || null
}

const handleAttachmentRemoved = (attachment) => {
  emit('remove-attachment', attachment.raw)
}

const handleSend = () => {
  if (sendLocked.value) return
  emit('send', { image: currentImage.value })
  currentImage.value = null
}

const toggleSendLock = () => {
  sendLocked.value = !sendLocked.value
  writeSendLockPreference(sendLocked.value)
}

const handleCompositionChange = (composing) => {
  isComposing.value = composing
}

const handleKeyDown = (e) => {
  if (props.sendButtonDisabled) {
    return
  }

  // 输入法组合态回车（keyCode 229）只用于确认候选词，不触发发送。
  if (isComposing.value || e.keyCode === 229) {
    return
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    handleSend()
  } else {
    emit('keydown', e)
  }
}

// 全局快捷键切换发送锁：Cmd/Ctrl + L（浏览器聚焦输入框时仍可触发）。
const handleGlobalKeyDown = (e) => {
  if ((e.metaKey || e.ctrlKey) && (e.key === 'l' || e.key === 'L')) {
    e.preventDefault()
    toggleSendLock()
  }
}

onMounted(() => {
  document.addEventListener('keydown', handleGlobalKeyDown)
})

onBeforeUnmount(() => {
  document.removeEventListener('keydown', handleGlobalKeyDown)
})

defineExpose({
  focus: () => inputRef.value?.focus(),
  closeOptions: () => inputRef.value?.closeOptions(),
  restoreImage,
  toggleSendLock,
  sendLocked
})
</script>

<style lang="less" scoped>
@import '@/components/composerStyles.less';

.agent-composer {
  width: 100%;
}

.composer-extra-region {
  .composer-top-attachment();
  display: flex;
  min-height: 36px;
  align-items: flex-start;
  gap: 6px;
  overflow-x: auto;
  padding: 4px 14px 2px;
}

.agent-composer.has-extra :deep(.input-box) {
  z-index: 1;
}

.input-actions-left {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-wrap: wrap;
}

.input-actions-right {
  display: flex;
  align-items: center;
  margin-right: 8px;
  gap: 2px;
}

.send-lock-btn {
  color: var(--gray-500);
  width: 30px;
  height: 30px;
  padding: 0;
  justify-content: center;
  margin-right: 6px;

  &.active {
    color: var(--main-700);
    background: var(--main-30);
    font-weight: 500;
  }
}

.input-top-stack {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 8px;
}

.attachment-preview-list {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.attachment-file-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 12px;
  width: 220px;
  min-width: 0;
  padding: 10px 34px 10px 12px;
  border: 1px solid var(--gray-150);
  border-radius: 12px;
  background: var(--gray-0);
  box-shadow: 0 1px 4px var(--shadow-0);
}

.attachment-file-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--main-700);
  background: var(--main-30);
}

.attachment-file-body {
  min-width: 0;
}

.attachment-file-name {
  overflow: hidden;
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-file-meta {
  margin-top: 2px;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.3;
}

.attachment-remove-btn {
  position: absolute;
  top: 6px;
  right: 6px;
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--gray-0);
  background: var(--gray-900);
  cursor: pointer;
  transition:
    background-color 0.15s ease,
    transform 0.15s ease;

  &:hover {
    background: var(--gray-700);
  }

  &:active {
    transform: scale(0.96);
  }
}

// 输入框操作按钮通用样式（穿透到 slot 内容）
:deep(.input-action-btn) {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  height: 30px;
  border-radius: 8px;
  font-size: 13px;
  color: var(--gray-600);
  cursor: pointer;
  transition: all 0.2s ease;
  user-select: none;
  background: transparent;
  border: none;

  &:hover {
    color: var(--gray-900);
    background: var(--gray-50);
  }

  &.active {
    color: var(--gray-900);
    background: var(--gray-100);
    font-weight: 500;
  }

  &.disabled {
    opacity: 0.5;
    cursor: not-allowed;
    pointer-events: none;
  }

  span {
    line-height: 1;
  }
}

// slot 内容的 hide-text 响应式样式
:deep(.hide-text) {
  @media (max-width: 768px) {
    display: none;
  }
}

@media (max-width: 768px) {
  .input-top-stack {
    gap: 8px;
    margin-bottom: 10px;
  }

  .attachment-file-card {
    width: min(220px, 100%);
  }
}
</style>
