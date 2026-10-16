<script setup>
import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'
import { getGovernanceDraft, setGovernanceDraft } from '@/utils/governanceDrafts'
import WorkspaceFileList from '@/components/workspace/WorkspaceFileList.vue'
import WorkspacePreviewPane from '@/components/workspace/WorkspacePreviewPane.vue'
import { projectFilesApi as api } from '@/apis/project_files_api'
import { normalizePreviewResponse } from '@/utils/file_preview'
import { describeBoardError } from '@/utils/governanceBoard'
import { useUserStore } from '@/stores/user'
const route = useRoute()
const props = defineProps({ projectId: { type: String, required: true } })
const user = useUserStore(),
  folder = ref('/'),
  search = ref(''),
  entries = ref([]),
  preview = ref(null),
  selected = ref(null),
  loading = ref(false),
  previewLoading = ref(false),
  busy = ref(false),
  error = ref(''),
  uploadInput = ref(null),
  dialog = ref(null),
  directoryName = ref('')
const fileDraft = ref(''),
  editingFile = ref(false)
const fileDirty = computed(
  () => selected.value && preview.value && fileDraft.value !== (preview.value.content || '')
)
const editableFile = computed(
  () =>
    ['markdown', 'text'].includes(preview.value?.previewType) &&
    /\.(?:md|markdown|mdx|txt)$/i.test(selected.value?.path || '')
)
watch(fileDraft, () => {
  if (selected.value && preview.value)
    setGovernanceDraft(
      user.uid,
      props.projectId,
      `project-file:${selected.value.path}`,
      fileDirty.value ? { content: fileDraft.value } : null
    )
})
useProjectThemeEdit('项目资料编辑', () => props.projectId, () => fileDirty.value || Boolean(dialog.value && directoryName.value), () => {fileDraft.value=preview.value?.content || '';dialog.value=null;directoryName.value=''}, () => busy.value)
function canLeaveFile() {
  return !fileDirty.value || window.confirm('文件有未保存修改，草稿已保留。是否离开当前文件？')
}
function beforeUnload(event) {
  if (fileDirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
onMounted(() => window.addEventListener('beforeunload', beforeUnload))
onBeforeRouteLeave(canLeaveFile)
let generation = 0,
  readSequence = 0,
  listSequence = 0
const capture = () => ({ project: props.projectId, user: user.uid, generation })
const current = (token) =>
  token.project === props.projectId && token.user === user.uid && token.generation === generation
const crumbs = computed(() => [
  { name: '项目资料', path: '/' },
  ...folder.value
    .split('/')
    .filter(Boolean)
    .map((name, index, parts) => ({ name, path: '/' + parts.slice(0, index + 1).join('/') }))
])
function failure(cause) {
  error.value = describeBoardError(cause)
  if ([401, 403].includes(cause?.status)) {
    entries.value = []
    preview.value = null
    selected.value = null
  }
}
function openDirectory() {
  directoryName.value = ''
  dialog.value = { kind: 'mkdir' }
}
function closePreview() {
  if (!canLeaveFile()) return
  selected.value = null
  preview.value = null
  readSequence++
}
async function load() {
  const token = capture(),
    request = ++listSequence,
    path = folder.value,
    query = search.value
  const active = () =>
    current(token) && request === listSequence && folder.value === path && search.value === query
  loading.value = true
  error.value = ''
  try {
    const value = await api.list(token.project, path, query)
    if (active()) entries.value = value.entries
  } catch (cause) {
    if (active()) failure(cause)
  } finally {
    if (active()) loading.value = false
  }
}
async function choose(entry, saved = false) {
  if (!saved && !canLeaveFile()) return
  editingFile.value = false
  if (entry.is_dir) {
    folder.value = entry.path
    search.value = ''
    selected.value = null
    preview.value = null
    return load()
  }
  const token = capture(),
    request = ++readSequence
  selected.value = entry
  preview.value = null
  previewLoading.value = true
  try {
    const response = await api.preview(token.project, entry.path)
    const file = await normalizePreviewResponse(response, entry)
    if (current(token) && request === readSequence) {
      preview.value = file
      fileDraft.value =
        getGovernanceDraft(token.user, token.project, `project-file:${entry.path}`)?.content ??
        file.content ??
        ''
    }
  } catch (cause) {
    if (current(token) && request === readSequence) failure(cause)
  } finally {
    if (current(token) && request === readSequence) previewLoading.value = false
  }
}
async function save(content) {
  const token = capture(),
    entry = selected.value
  if (!entry || busy.value) return
  busy.value = true
  try {
    await api.save(token.project, entry.path, content)
    if (current(token) && selected.value?.path === entry.path) {
      setGovernanceDraft(token.user, token.project, `project-file:${entry.path}`, null)
      await choose(entry, true)
    }
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    if (current(token)) busy.value = false
  }
}
async function download(entry) {
  const token = capture()
  try {
    const response = await api.download(token.project, entry.path)
    if (!current(token)) return
    const blob = await response.blob(),
      url = URL.createObjectURL(blob),
      link = document.createElement('a')
    link.href = url
    link.download = entry.name
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (cause) {
    if (current(token)) failure(cause)
  }
}
async function upload(event) {
  const token = capture(),
    files = Array.from(event.target.files || [])
  if (!files.length || busy.value) return
  busy.value = true
  try {
    await api.upload(token.project, folder.value, files)
    if (current(token)) await load()
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    event.target.value = ''
    if (current(token)) busy.value = false
  }
}
async function submit() {
  const target = dialog.value,
    token = capture()
  if (busy.value || !target) return
  busy.value = true
  error.value = ''
  try {
    if (target.kind === 'mkdir') await api.mkdir(token.project, folder.value, directoryName.value)
    else await api.delete(token.project, target.entry.path)
    if (current(token)) {
      dialog.value = null
      if (selected.value?.path === target.entry?.path) {
        selected.value = null
        preview.value = null
      }
      await load()
    }
  } catch (cause) {
    if (current(token)) failure(cause)
  } finally {
    if (current(token)) busy.value = false
  }
}
watch(
  () => [props.projectId, user.uid],
  () => {
    generation++
    readSequence++
    folder.value = '/'
    entries.value = []
    preview.value = null
    selected.value = null
    dialog.value = null
    busy.value = false
    void load()
    if (route.query.open)
      void choose({
        path: String(route.query.open),
        name: String(route.query.open).split('/').pop(),
        is_dir: false
      })
  },
  { immediate: true }
)
watch(
  () => route.query.open,
  (path) => {
    if (path)
      void choose({ path: String(path), name: String(path).split('/').pop(), is_dir: false })
  }
)
onBeforeUnmount(() => {
  window.removeEventListener('beforeunload', beforeUnload)
  generation++
  readSequence++
})
</script>
<template>
  <section class="project-files-workspace" aria-label="项目资料">
    <div class="files-page-actions"><a-button type="primary" :loading="busy" @click="uploadInput.click()">上传资料</a-button><input ref="uploadInput" type="file" multiple hidden @change="upload" /></div>
    <section class="files-panel"><h2>文件</h2><div class="files-tools"><a-input-search v-model:value="search" aria-label="搜索当前项目资料" placeholder="搜索项目文件" @search="load" /><div><a-button :disabled="busy" @click="openDirectory">新建目录</a-button><a-button type="text" :loading="loading" @click="load">刷新</a-button></div></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <div class="files-layout" :class="{ 'with-preview': selected }">
      <WorkspaceFileList
        :entries="entries"
        :current-path="folder"
        :selected-path="selected?.path || ''"
        :loading="loading"
        :readonly="busy"
        root-label="项目资料"
        :breadcrumb-items="crumbs"
        @select-entry="choose"
        @breadcrumb-click="
          (path) => {
            folder = path
            search = ''
            load()
          }
        "
        @delete-entry="(entry) => (dialog = { kind: 'delete', entry })"
        @delete-selected="error = '请逐项确认需要删除的资料'"
        @download-entry="download"
      />
      <section v-if="selected" class="project-file-preview">
        <div v-if="editableFile" class="file-edit-tools">
          <a-button :disabled="busy" @click="editingFile = !editingFile">{{
            editingFile ? '阅读（保留草稿）' : '编辑正文'
          }}</a-button
          ><span v-if="fileDirty">有未保存草稿</span
          ><a-button v-if="editingFile" type="primary" :loading="busy" @click="save(fileDraft)"
            >保存</a-button
          >
        </div>
        <a-textarea
          v-if="editingFile"
          v-model:value="fileDraft"
          aria-label="项目文件正文"
          :disabled="busy"
          :auto-size="{ minRows: 18 }"
        /><WorkspacePreviewPane
          v-else
          :file="preview"
          :file-path="selected.path"
          :loading="previewLoading"
          :editable="false"
          :saving="busy"
          @close="closePreview"
          @save="save"
        />
      </section>
    </div>
    <details class="linked-resources"><summary>关联知识与平台资源</summary><RouterLink :to="{name:'ProjectSettings',params:{project_id:projectId}}">在项目设置中维护资源连接与知识库关联</RouterLink></details></section>
    <a-modal
      :open="!!dialog"
      :title="dialog?.kind === 'mkdir' ? '新建项目目录' : '永久删除项目资料'"
      :confirm-loading="busy"
      :ok-button-props="{ danger: dialog?.kind === 'delete' }"
      :mask-closable="false"
      :closable="!busy"
      :cancel-button-props="{ disabled: busy }"
      @ok="submit"
      @cancel="dialog = null"
      ><a-alert v-if="error" type="error" :message="error" /><a-input
        v-if="dialog?.kind === 'mkdir'"
        v-model:value="directoryName"
        aria-label="新目录名称"
        :disabled="busy"
      />
      <p v-else>
        确认永久删除「{{ dialog?.entry.name }}」？此操作无法撤销，目录内资料也会删除。
      </p></a-modal
    >
  </section>
</template>
<style scoped lang="less">
.files-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 24px;
  > :deep(.ant-input-search) {
    max-width: 360px;
    min-width: 100px;
  }
  > div {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
  }
}
.files-layout {
  background: var(--gray-0);
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  min-width: 0;
  overflow: hidden;
}
.with-preview {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, 1fr);
  min-height: 650px;
}
@media (max-width: 1024px) {
  .with-preview {
    grid-template-columns: 1fr;
  }
  .files-tools {
    flex-wrap: wrap;
  }
}

.file-edit-tools {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px;
}
.project-file-preview {
  min-width: 0;
  padding: 12px;
}

.files-page-actions { display:flex; justify-content:flex-end; min-height:72px; padding:20px 0; margin-bottom:4px; }.files-panel { padding:24px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; min-width:0; >h2 { font-size:19px; margin:0 0 18px; } }.files-tools { justify-content:flex-start; gap:12px; :deep(.ant-input-search) { max-width:260px; } >div { display:flex; gap:8px; } }.linked-resources { margin-top:20px; font-size:13px; >summary { cursor:pointer; padding:8px 0; } }
@media(max-width:760px) { .files-panel { padding:18px; }.files-tools { flex-wrap:wrap; } }
</style>
