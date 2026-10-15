<script setup>
import { onBeforeUnmount, ref, useId } from 'vue'
import { message } from 'ant-design-vue'
import { Upload, RefreshCw } from '@lucide/vue'
import FallbackAvatar from './common/FallbackAvatar.vue'
import { userApi } from '@/apis/user_api'
import { generatePixelAvatar } from '@/utils/pixelAvatar'
import { MAX_IMAGE_UPLOAD_SIZE_BYTES, MAX_IMAGE_UPLOAD_SIZE_MB } from '@/utils/upload_limits'

const props = defineProps({ icon: { type: [String, null], default: '' }, slug: { type: [String, null], default: '' }, slugLocked: Boolean, disabled: Boolean, scopeKey: { type: String, required: true }, name: { type: [String, null], default: '' } })
const emit = defineEmits(['update:icon', 'update:slug', 'uploading'])
const uploading = ref(false)
const slugInputId = `project-slug-${useId()}`
let mounted = true
onBeforeUnmount(() => { mounted = false })

/** 复用智能体图片上传，迟到响应不覆盖切换后的项目。 */
const beforeUpload = (file) => {
  if (!file.type.startsWith('image/')) { message.error('只能上传图片文件'); return false }
  if (file.size > MAX_IMAGE_UPLOAD_SIZE_BYTES) { message.error(`图片大小不能超过 ${MAX_IMAGE_UPLOAD_SIZE_MB}MB`); return false }
  const scope = props.scopeKey
  uploading.value = true
  emit('uploading', true)
  userApi.uploadImage(file).then((data) => {
    if (mounted && props.scopeKey === scope) {
      emit('update:icon', data.image_url || data.url || '')
      message.success('图标已上传，保存项目后生效')
    }
  }).catch((error) => {
    if (mounted && props.scopeKey === scope) message.error(error.message || '图标上传失败')
  }).finally(() => {
    if (mounted) { uploading.value = false; emit('uploading', false) }
  })
  return false
}
</script>

<template>
  <div class="project-identity-fields" :class="{ 'identity-heading': !!$slots.name }">
    <div>
      <label v-if="!$slots.name">项目图标</label>
      <a-upload :show-upload-list="false" :before-upload="beforeUpload" :disabled="disabled || uploading" accept="image/*">
        <button type="button" class="project-icon-upload" :disabled="disabled || uploading" aria-label="上传项目图标">
          <FallbackAvatar :src="icon" :default-src="generatePixelAvatar(scopeKey)" :name="name" :seed="scopeKey" kind="agent" shape="rounded" :size="56" :alt="`${name || '项目'}图标`" />
          <span class="icon-upload-caption"><RefreshCw v-if="uploading" :size="16" /><Upload v-else :size="16" />{{ uploading ? '上传中…' : icon ? '更换图标' : '上传图标' }}</span>
        </button>
      </a-upload>
      <p v-if="!$slots.name">图片最多 {{ MAX_IMAGE_UPLOAD_SIZE_MB }}MB；上传后仍需保存项目。</p>
    </div>
    <div class="project-slug-field">
      <slot name="name" />
      <label v-if="!slugLocked || !$slots.name" :for="slugLocked ? undefined : slugInputId">项目标识 slug</label>
      <p v-if="slugLocked" class="locked-slug">{{ slug }}</p>
      <a-input v-else :id="slugInputId" :value="slug" :readonly="slugLocked" :disabled="disabled" :maxlength="64" placeholder="可选，1—64位，支持大小写字母" @update:value="emit('update:slug', $event)" />
      <p v-if="!slugLocked">字母、数字或连字符，首尾为字母或数字；全局唯一且不区分大小写，设定后不可修改。</p>
    </div>
  </div>
</template>

<style scoped lang="less">
.project-identity-fields { display: grid; grid-template-columns: 180px minmax(0, 1fr); gap: 20px; margin-bottom: 18px;
  label { display: block; font-size: 13px; color: var(--gray-800); margin-bottom: 8px; }
  p { font-size: 12px; color: var(--gray-600); line-height: 1.6; margin: 8px 0 0; }
}
.project-icon-upload { display: flex; align-items: center; gap: 10px; border: 1px solid var(--gray-200); background: var(--gray-0); color: var(--main-color); padding: 5px; border-radius: 8px; cursor: pointer;
  .icon-upload-caption { display: flex; align-items: center; gap: 5px; font-size: 12px; }
  &:disabled { cursor: not-allowed; opacity: .6; }
  &:focus-visible { outline: 2px solid var(--main-color); outline-offset: 2px; }
}
@media (max-width:600px) { .project-identity-fields { grid-template-columns: minmax(0,1fr); gap: 16px; } }

.project-slug-field .locked-slug { color:var(--color-text-secondary); margin:6px 0 0; font-size:14px; overflow-wrap:anywhere; }
.identity-heading { grid-template-columns:auto minmax(0,1fr); align-items:center; gap:20px; margin-bottom:28px; .project-icon-upload { padding:0; border:0; background:transparent; position:relative; >.icon-upload-caption { position:absolute; inset:0; opacity:0; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:8px; justify-content:center; font-size:11px; } &:hover>.icon-upload-caption, &:focus-visible>.icon-upload-caption { opacity:1; } } .project-slug-field { min-width:0; } }
</style>
