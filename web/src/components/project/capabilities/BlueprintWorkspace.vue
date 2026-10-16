<script setup>
import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  Archive,
  Columns2,
  Eye,
  ChevronDown,
  PanelTop,
  FileText,
  History,
  MoreHorizontal,
  Pencil,
  Plus,
  RefreshCw
} from '@lucide/vue'
import { formatFullDateTime } from '@/utils/time'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { governanceBoardApi as api } from '@/apis/governance_board_api'
import { useUserStore } from '@/stores/user'
import { describeBoardError } from '@/utils/governanceBoard'
import { displayBlueprintName, blueprintDocumentHeading, blueprintDocumentBody, normalizeBlueprintName } from '@/utils/blueprintName'
import { blueprintTemplateContent, blueprintTemplates } from '@/utils/blueprintTemplates'
import {
  clearGovernanceDrafts,
  getGovernanceDraft,
  setGovernanceDraft
} from '@/utils/governanceDrafts'

const blueprintMenuOpen = ref(false)
const documentHeading = name => blueprintDocumentHeading(name, entries.value[name]?.saved)
const props = defineProps({ projectId: { type: String, required: true } })
const route = useRoute(),
  router = useRouter(),
  user = useUserStore()
const documents = ref([]),
  archives = ref([]),
  archiveDirectoryOpen = ref(false),
  entries = ref({})
const selected = ref(''),
  layout = ref('detail'),
  expanded = ref({}),
  editing = ref({})
const loading = ref(false),
  busy = ref(false),
  error = ref(''),
  shared = ref(false)
const history = ref(null),
  historyLoading = ref(false),
  historyError = ref(''),
  origin = ref(null)
const content = ref(null),
  dialog = ref(null),
  dialogName = ref(''),
  dialogContent = ref(''),
  dialogTemplate = ref('blank'),
  dialogError = ref('')
let sequence = 0,
  archiveSequence = 0,
  scope = null
/** 将归档存储时间转为可读的本地时间，不向日常入口展示文件标识。 */
function archiveLabel(value) {
  const raw = String(value || '')
  if (!/^\d{8}T\d{12}Z$/.test(raw)) return raw || '时间未记录'
  return formatFullDateTime(`${raw.slice(0,4)}-${raw.slice(4,6)}-${raw.slice(6,8)}T${raw.slice(9,11)}:${raw.slice(11,13)}:${raw.slice(13,15)}.${raw.slice(15,18)}Z`)
}
const currentArchives = computed(() =>
  archives.value.filter((item) => item.name === selected.value)
)
function openHistoryMenu(key) {
  if (key === 'all-archives') archiveDirectoryOpen.value = true
  else void showHistory(key)
}
function chooseArchive(name) {
  archiveDirectoryOpen.value = false
  return showHistory(name)
}
const visible = computed(() =>
  layout.value === 'drawer'
    ? documents.value
    : documents.value.filter((item) => item.name === selected.value)
)
const dirty = computed(() =>
  Object.values(entries.value).some((item) => item.content !== item.saved)
)
const dialogDirty = computed(
  () =>
    dialog.value?.kind === 'create' &&
    (dialogName.value || dialogContent.value !== blueprintTemplateContent(dialogTemplate.value))
)
const current = (token) =>
  token.sequence === sequence && token.project === props.projectId && token.user === user.uid
const token = () => ({ sequence, project: props.projectId, user: user.uid })
const draftKey = (name) => `blueprint:${name}`

/** 草稿按身份、项目与文件隔离，保留离开前的正文。 */
function persist() {
  if (!scope || scope.project !== props.projectId || scope.user !== user.uid) return
  for (const [name, item] of Object.entries(entries.value)) {
    setGovernanceDraft(
      scope.user,
      scope.project,
      draftKey(name),
      item.content !== item.saved ? { content: item.content } : null
    )
  }
}
watch(entries, persist, { deep: true, flush: 'sync' })

/** 失权后清空可见数据及该身份草稿。 */
function report(cause, missingProject = false) {
  error.value = describeBoardError(cause)
  if (
    [401, 403].includes(cause?.status || cause?.response?.status) ||
    (missingProject && (cause?.status || cause?.response?.status) === 404)
  ) {
    clearGovernanceDrafts(user.uid, props.projectId)
    scope = null
    entries.value = {}
    documents.value = []
    archives.value = []
    archiveDirectoryOpen.value = false
    history.value = null
    dialog.value = null
  }
}

/** 回读当前文件，不用写入响应冒充文件验证。 */
async function read(name, captured = token()) {
  const value = await api.getBlueprint(captured.project, name)
  if (!current(captured)) return
  const before = entries.value[name]
  const draft = getGovernanceDraft(captured.user, captured.project, draftKey(name))
  const text =
    before && before.content !== before.saved ? before.content : (draft?.content ?? value.content)
  entries.value = { ...entries.value, [name]: { content: text, saved: value.content } }
}

/** 加载目录和归档，异步结果只交给原项目身份。 */
async function load() {
  const captured = token()
  loading.value = true
  error.value = ''
  try {
    const [list, old] = await Promise.all([
      api.listBlueprints(captured.project),
      api.listBlueprintArchives(captured.project)
    ])
    if (!current(captured)) return
    documents.value = list.documents || []
    archives.value = old.documents || []
    shared.value = Boolean(list.shared_workdir)
    if (route.query.blueprint) selected.value = String(route.query.blueprint)
    else if (!documents.value.some((item) => item.name === selected.value))
      selected.value = documents.value[0]?.name || ''
    await Promise.all(documents.value.map((item) => read(item.name, captured)))
    if (current(captured) && selected.value)
      expanded.value = { ...expanded.value, [selected.value]: true }
  } catch (cause) {
    if (current(captured)) report(cause, true)
  } finally {
    if (current(captured)) loading.value = false
  }
}

/** 选择抽屉文档先展开，再在当前内容容器定位。 */
async function choose(name) {
  selected.value = name
  expanded.value = { ...expanded.value, [name]: true }
  await router.push({ query: { ...route.query, blueprint: name } })
  await nextTick()
  if (layout.value === 'drawer')
    Array.from(content.value?.querySelectorAll('[data-blueprint]') || [])
      .find((node) => node.dataset.blueprint === name)
      ?.scrollIntoView({ block: 'start', behavior: 'auto' })
}

/** 历史首次进入捕获来源，连续切换不会覆盖原上下文。 */
async function showHistory(name) {
  if (!name) return
  if (!origin.value)
    origin.value = {
      selected: selected.value,
      layout: layout.value,
      expanded: { ...expanded.value },
      editing: { ...editing.value },
      top: content.value?.scrollTop || 0
    }
  const captured = token(),
    request = ++archiveSequence
  history.value = { archive_name: name }
  historyLoading.value = true
  historyError.value = ''
  try {
    const value = await api.getBlueprintArchive(captured.project, name)
    if (current(captured) && request === archiveSequence)
      history.value = { ...value, archive_name: name }
  } catch (cause) {
    if (current(captured) && request === archiveSequence) {
      historyError.value = describeBoardError(cause)
      if ([401, 403].includes(cause?.status)) report(cause)
    }
  } finally {
    if (current(captured) && request === archiveSequence) historyLoading.value = false
  }
}
async function returnFromHistory() {
  archiveSequence++
  history.value = null
  historyLoading.value = false
  const source = origin.value
  origin.value = null
  if (source) {
    selected.value = source.selected
    layout.value = source.layout
    expanded.value = source.expanded
    editing.value = source.editing
    await nextTick()
    if (content.value) content.value.scrollTop = source.top
  }
  await nextTick()
  content.value?.querySelector('textarea, [data-blueprint] button')?.focus({ preventScroll: true })
}

/** 保存准确文件后重新读取，不覆盖请求期间继续输入的草稿。 */
async function save(name) {
  const captured = token(),
    submitted = entries.value[name]?.content
  if (busy.value || submitted === undefined) return
  busy.value = true
  error.value = ''
  try {
    await api.putBlueprint(captured.project, name, submitted)
    const value = await api.getBlueprint(captured.project, name)
    if (!current(captured)) return
    entries.value = {
      ...entries.value,
      [name]: { content: entries.value[name].content, saved: value.content }
    }
    if (entries.value[name].content === value.content)
      editing.value = { ...editing.value, [name]: false }
  } catch (cause) {
    if (current(captured)) report(cause)
  } finally {
    if (current(captured)) busy.value = false
  }
}

function toggleEditing(name) {
  expanded.value[name] = true
  editing.value[name] = !editing.value[name]
}
function openDialog(kind, name = '', archived = false) {
  dialog.value = { kind, name, archived, scope: token() }
  dialogError.value = ''
  dialogName.value = kind === 'rename' ? displayBlueprintName(name) : ''
  if (kind === 'create') {
    const draft = getGovernanceDraft(user.uid, props.projectId, 'blueprint-create')
    dialogName.value = draft?.name || ''
    dialogContent.value = draft?.content || ''
    dialogTemplate.value = draft?.template || 'blank'
  }
}
watch([dialogName, dialogContent, dialogTemplate], () => {
  if (dialog.value?.kind === 'create' && current(dialog.value.scope))
    setGovernanceDraft(user.uid, props.projectId, 'blueprint-create', {
      name: dialogName.value,
      content: dialogContent.value,
      template: dialogTemplate.value
    })
})
function changeTemplate(value) {
  if (
    dialogContent.value !== blueprintTemplateContent(dialogTemplate.value) &&
    !window.confirm('切换模板会替换当前新建正文。是否继续？')
  )
    return
  dialogTemplate.value = value
  dialogContent.value = blueprintTemplateContent(value)
}

/** 管理动作保持原文件Owner，失败保留输入并标明错误。 */
async function submitDialog() {
  const target = dialog.value
  if (!target || busy.value || !current(target.scope)) return
  const name = ['create', 'rename'].includes(target.kind)
    ? normalizeBlueprintName(dialogName.value)
    : target.name
  if (!name) {
    dialogError.value = '请输入有效名称，不含空格或路径分隔符，最多120字。'
    return
  }
  if (
    ['archive', 'delete'].includes(target.kind) &&
    !target.archived &&
    entries.value[target.name]?.content !== entries.value[target.name]?.saved
  ) {
    dialogError.value = '此蓝图有未保存草稿，请先保存。'
    return
  }
  const captured = target.scope
  busy.value = true
  dialogError.value = ''
  try {
    if (target.kind === 'create') {
      await api.createBlueprint(captured.project, name, dialogContent.value)
      if (!current(captured)) return
      setGovernanceDraft(captured.user, captured.project, 'blueprint-create', null)
      selected.value = name
      expanded.value[name] = true
    } else if (target.kind === 'rename') {
      await api.renameBlueprint(captured.project, target.name, name)
      if (!current(captured)) return
      if (entries.value[target.name])
        entries.value = { ...entries.value, [name]: entries.value[target.name] }
      delete entries.value[target.name]
      setGovernanceDraft(captured.user, captured.project, draftKey(target.name), null)
      selected.value = name
      expanded.value[name] = true
    } else if (target.kind === 'archive') await api.archiveBlueprint(captured.project, target.name)
    else if (target.archived) await api.deleteBlueprintArchive(captured.project, target.name)
    else await api.deleteBlueprint(captured.project, target.name)
    if (!current(captured)) return
    if (['archive', 'delete'].includes(target.kind) && !target.archived) {
      delete entries.value[target.name]
      setGovernanceDraft(captured.user, captured.project, draftKey(target.name), null)
    }
    if (['create', 'rename'].includes(target.kind))
      await router.replace({ query: { ...route.query, blueprint: name } })
    if (
      ['archive', 'delete'].includes(target.kind) &&
      !target.archived &&
      route.query.blueprint === target.name
    ) {
      const query = { ...route.query }
      delete query.blueprint
      selected.value = ''
      await router.replace({ query })
    }
    if (target.archived) await returnFromHistory()
    dialog.value = null
    await load()
  } catch (cause) {
    if (current(captured)) {
      dialogError.value = describeBoardError(cause)
      if ([401, 403].includes(cause?.status)) report(cause)
    }
  } finally {
    if (current(captured)) busy.value = false
  }
}
useProjectThemeEdit('蓝图编辑／新建', () => props.projectId, () => dirty.value || dialogDirty.value, () => {for(const item of Object.values(entries.value)) item.content=item.saved;dialog.value=null;persist()}, () => busy.value)
function beforeUnload(event) {
  if (dirty.value || dialogDirty.value) {
    event.preventDefault()
    event.returnValue = ''
  }
}
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(
  () =>
    (!dirty.value && !dialogDirty.value) ||
    window.confirm('有未保存的蓝图草稿，已在本标签页保留。是否离开？')
)
onBeforeUnmount(() => {
  persist()
  sequence++
  archiveSequence++
  window.removeEventListener('beforeunload', beforeUnload)
})
watch(
  () => route.query.blueprint,
  async (name) => {
    if (!name) return
    selected.value = String(name)
    expanded.value = { ...expanded.value, [name]: true }
    await nextTick()
    if (layout.value === 'drawer')
      Array.from(content.value?.querySelectorAll('[data-blueprint]') || [])
        .find((node) => node.dataset.blueprint === name)
        ?.scrollIntoView({ block: 'start' })
  }
)
watch(
  () => [props.projectId, user.uid],
  () => {
    sequence++
    archiveSequence++
    scope = null
    documents.value = []
    archives.value = []
    archiveDirectoryOpen.value = false
    entries.value = {}
    selected.value = ''
    expanded.value = {}
    editing.value = {}
    history.value = null
    origin.value = null
    dialog.value = null
    busy.value = false
    scope = { project: props.projectId, user: user.uid }
    void load()
  },
  { immediate: true }
)
</script>

<template>
  <section class="blueprint-workspace" aria-label="蓝图文档工作区">
    <div class="blueprint-toolbar">
      <a-dropdown v-model:open="blueprintMenuOpen" :trigger="['hover','click']"><button type="button" class="blueprint-selector" aria-label="切换蓝图" aria-haspopup="menu" :aria-expanded="blueprintMenuOpen" :disabled="loading || !!history"><FileText :size="17" /><span>{{ selected ? displayBlueprintName(selected) : '选择蓝图' }}</span><ChevronDown :size="16" /></button><template #overlay><a-menu @click="({key}) => { blueprintMenuOpen = false; choose(key) }"><a-menu-item v-for="item in documents" :key="item.name">{{ documentHeading(item.name) }}</a-menu-item></a-menu></template></a-dropdown>
      <div class="toolbar-actions">
        <div class="view-switch" aria-label="蓝图布局"><button type="button" :aria-pressed="layout === 'detail'" :disabled="!!history" aria-label="详情模式" @click="layout = 'detail'"><PanelTop :size="18" /></button><button type="button" :aria-pressed="layout === 'drawer'" :disabled="!!history" aria-label="抽屉模式" @click="layout = 'drawer'"><Columns2 :size="18" /></button></div>
        <a-dropdown :trigger="['click']"
          ><button type="button" aria-label="蓝图历史"><History :size="18" /></button
          ><template #overlay
            ><a-menu @click="({ key }) => openHistoryMenu(key)"
              ><a-menu-item v-for="item in currentArchives" :key="item.archive_name"
                >{{ documentHeading(item.name) }} · {{ archiveLabel(item.archived_at) }}</a-menu-item
              ><a-menu-item v-if="!currentArchives.length" disabled>当前蓝图暂无归档</a-menu-item
              ><a-menu-divider /><a-menu-item key="all-archives"
                >全部归档蓝图 · {{ archives.length }}</a-menu-item
              ></a-menu
            ></template
          ></a-dropdown
        >
        <button type="button" aria-label="刷新蓝图" :disabled="busy || loading" @click="load">
          <RefreshCw :size="18" />
        </button>
        <a-button type="primary" :disabled="busy" @click="openDialog('create')"
          ><Plus :size="16" />新建</a-button
        >
      </div>
    </div>
    <a-modal v-model:open="archiveDirectoryOpen" title="全部归档蓝图" :footer="null" :width="640">
      <p v-if="!archives.length">暂无归档蓝图。</p>
      <ul class="archive-directory">
        <li v-for="item in archives" :key="item.archive_name">
          <a-button type="link" @click="chooseArchive(item.archive_name)"
            >{{ documentHeading(item.name) }} · {{ archiveLabel(item.archived_at) }}</a-button
          >
        </li>
      </ul>
    </a-modal>
    <a-alert
      v-if="shared"
      type="info"
      show-icon
      message="多个项目共用此目录；修改、重命名和归档作用于同一文件。"
    />
    <a-alert
      v-if="selected && !loading && !documents.some((item) => item.name === selected)"
      type="warning"
      message="指定蓝图不存在或无权访问，请从目录选择；原地址保留。"
    />
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <div v-if="loading" role="status" class="blueprint-state">正在读取蓝图…</div>
    <div ref="content" class="blueprint-content">
      <article v-if="history" class="blueprint-document history-document">
        <header>
          <strong>归档蓝图 · 只读</strong><a-button @click="returnFromHistory">返回</a-button>
        </header>
        <p class="metadata">{{ displayBlueprintName(history.name || selected) }} · {{ archiveLabel(history.archived_at) }}</p>
        <p v-if="historyLoading" role="status">正在读取归档…</p>
        <a-alert v-else-if="historyError" type="error" :message="historyError"
          ><template #action
            ><a-button @click="showHistory(history.archive_name)">重试</a-button></template
          ></a-alert
        >
        <MarkdownPreview v-else :content="history.content || '此归档没有正文。'" />
        <a-button
          danger
          :disabled="busy || historyLoading || !!historyError"
          @click="openDialog('delete', history.archive_name, true)"
          >永久删除此归档</a-button
        >
      </article>
      <template v-else>
        <div v-if="!documents.length && !loading && !error" class="blueprint-state">
          <FileText :size="28" />
          <p>还没有蓝图，从目标与预期结果开始。</p>
          <a-button @click="openDialog('create')">新建蓝图</a-button>
        </div>
        <article
          v-for="item in visible"
          :key="item.name"
          :data-blueprint="item.name"
          class="blueprint-document"
        >
          <header>
            <h1 v-if="layout === 'detail'" class="document-heading">{{ documentHeading(item.name) }}</h1>
            <button v-else
              class="document-title"
              type="button"
              :aria-expanded="layout === 'detail' || !!expanded[item.name]"
              @click="expanded[item.name] = !expanded[item.name]"
            >
              {{ documentHeading(item.name) }}
            </button>
            <div class="document-actions">
              <button type="button" aria-label="阅览" :aria-pressed="!editing[item.name]" :disabled="!entries[item.name] || busy" @click="editing[item.name] = false"><Eye :size="17" /></button><button type="button" aria-label="编辑" :aria-pressed="!!editing[item.name]" :disabled="!entries[item.name] || busy" @click="!editing[item.name] && toggleEditing(item.name)"><Pencil :size="17" /></button>
              <a-dropdown :trigger="['click']"
                ><button
                  type="button"
                  :aria-label="`${documentHeading(item.name)}更多操作`"
                  :disabled="busy"
                >
                  <MoreHorizontal :size="18" /></button
                ><template #overlay
                  ><a-menu @click="({ key }) => openDialog(key, item.name)"
                    ><a-menu-item key="rename">重命名</a-menu-item
                    ><a-menu-item key="archive"><Archive :size="14" />归档</a-menu-item
                    ><a-menu-divider /><a-menu-item key="delete" danger
                      >永久删除</a-menu-item
                    ></a-menu
                  ></template
                ></a-dropdown
              >
            </div>
          </header>
          <div v-if="layout === 'detail' || expanded[item.name]" class="document-body">
            <template v-if="entries[item.name]">
              <template v-if="editing[item.name]"
                ><a-textarea
                  v-model:value="entries[item.name].content"
                  :aria-label="`${documentHeading(item.name)}正文`"
                  :auto-size="{ minRows: 16 }"
                />
                <div class="save-tools">
                  <span role="status">{{
                    entries[item.name].content !== entries[item.name].saved
                      ? '有未保存草稿'
                      : '正文已保存'
                  }}</span
                  ><a-button :disabled="busy" @click="editing[item.name] = false"
                    >阅读（保留草稿）</a-button
                  ><a-button type="primary" :loading="busy" @click="save(item.name)">保存</a-button>
                </div></template
              >
              <template v-else
                ><p
                  v-if="entries[item.name].content !== entries[item.name].saved"
                  class="draft-hint"
                >
                  有未保存草稿，切换编辑可继续。
                </p>
                <MarkdownPreview :content="blueprintDocumentBody(entries[item.name].saved) || '这份蓝图尚无正文。'"
              /></template>
            </template>
          </div>
        </article>
      </template>
    </div>
    <a-modal
      :open="!!dialog"
      :title="
        { create: '新建蓝图', rename: '重命名蓝图', archive: '归档蓝图', delete: '永久删除蓝图' }[
          dialog?.kind
        ]
      "
      :width="dialog?.kind === 'create' ? 760 : 480"
      :confirm-loading="busy"
      :ok-text="
        { create: '创建', rename: '保存名称', archive: '归档', delete: '永久删除' }[dialog?.kind]
      "
      :ok-button-props="{ danger: dialog?.kind === 'delete' }"
      :mask-closable="false"
      :closable="!busy"
      :keyboard="!busy"
      :cancel-button-props="{ disabled: busy }"
      @ok="submitDialog"
      @cancel="dialog = null"
    >
      <a-alert
        v-if="dialogError"
        type="error"
        show-icon
        :message="dialogError"
        class="dialog-error"
      />
      <a-form
        v-if="['create', 'rename'].includes(dialog?.kind)"
        layout="vertical"
        @submit.prevent="submitDialog"
      >
        <a-form-item label="名称"
          ><a-input
            v-model:value="dialogName"
            aria-label="蓝图名称"
            :disabled="busy"
            :maxlength="120"
            autofocus
            placeholder="名称自动补全 .md"
        /></a-form-item>
        <template v-if="dialog?.kind === 'create'"
          ><a-form-item label="起草模板"
            ><a-select
              :value="dialogTemplate"
              aria-label="起草模板"
              :disabled="busy"
              :options="blueprintTemplates"
              @change="changeTemplate" /></a-form-item
          ><a-form-item label="正文"
            ><a-textarea
              v-model:value="dialogContent"
              aria-label="新蓝图正文"
              :disabled="busy"
              :auto-size="{ minRows: 10, maxRows: 18 }" /></a-form-item
        ></template>
      </a-form>
      <p v-else>
        {{ displayBlueprintName(dialog?.name)
        }}{{
          dialog?.kind === 'archive'
            ? '将移至历史，归档正文可继续查阅。'
            : '将从共享目录永久删除，无法撤销。请确认已保存所需内容。'
        }}
      </p>
    </a-modal>
  </section>
</template>

<style scoped lang="less">
.blueprint-workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  gap: 16px;
}
.blueprint-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 20px 0;
  min-height: 72px;
  > :deep(.ant-select) {
    width: 260px;
    max-width: 45%;
    min-width: 80px;
    flex-shrink: 1;
  }
}
.toolbar-actions :deep(.ant-btn) { display: inline-flex; align-items: center; gap: 6px; }
.toolbar-actions,
.document-actions,
.save-tools {
  display: flex;
  align-items: center;
  gap: 8px;
}
button {
  color: var(--color-text);
  cursor: pointer;
}
.toolbar-actions > button:not(.ant-btn),
.document-actions > button:not(.ant-btn) {
  display: grid;
  place-items: center;
  width: 36px;
  min-height: 36px;
  border: 0;
  border-radius: 6px;
  background: transparent;
}
button:disabled {
  cursor: default;
  opacity: 0.45;
}
button:focus-visible {
  outline: 2px solid var(--main-color);
  outline-offset: 2px;
}
.blueprint-content {
  flex: 1;
  min-height: 0;
  overflow: auto;
  scroll-padding: 16px;
}
.blueprint-document {
  max-width: 960px;
  margin: 0 auto 24px;
  padding: 28px 32px 40px;
  background: var(--gray-0);
  border: 1px solid var(--gray-150);
  border-radius: 10px;
  overflow-wrap: anywhere;
  > header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
}
.document-title {
  font-size: 20px;
  line-height: 1.5;
  font-weight: 600;
  text-align: left;
  border: 0;
  padding: 0;
  background: transparent;
  overflow-wrap: anywhere;
}
.document-body {
  margin-top: 24px;
  font-size: 16px;
  line-height: 1.8;
  :deep(.yk-markdown-preview) {
    font-size: 16px;
    line-height: 1.8;
  }
}
.save-tools {
  margin-top: 16px;
  flex-wrap: wrap;
  justify-content: flex-end;
  > span {
    margin-right: auto;
  }
}
.metadata,
.draft-hint,
.save-tools > span {
  font-size: 13px;
  color: var(--color-text-secondary);
}
.blueprint-state {
  padding: 48px 16px;
  text-align: center;
  color: var(--color-text-secondary);
}
.dialog-error {
  margin-bottom: 16px;
}
@media (max-width: 768px) {
  .blueprint-document {
    padding: 20px 16px;
  }
  .blueprint-toolbar {
    gap: 4px;
  }
  .toolbar-actions {
    gap: 2px;
    :deep(.ant-btn svg) { display: none; }
  }
  .toolbar-actions > button:not(.ant-btn),
  .document-actions > button:not(.ant-btn) {
    width: 40px;
    min-height: 44px;
  }
}

.blueprint-workspace { max-width:960px; margin:0 auto; }.blueprint-toolbar :deep(.ant-select-selector) { background:transparent!important; border:0!important; box-shadow:none!important; padding-left:0!important; }

.view-switch { display:flex; gap:2px; padding-right:10px; border-right:1px solid var(--gray-150); button { display:grid; place-items:center; padding:7px; min-width:38px; min-height:38px; border:0; background:none; border-radius:6px; } }.view-switch button[aria-pressed='true'],.document-actions button[aria-pressed='true'] { color:var(--main-color); background:var(--main-10); }

.blueprint-selector { display:flex; align-items:center; gap:9px; max-width:min(52%,420px); background:none; border:0; padding:0; min-width:0; font-size:13px; span { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } }.document-heading { font-size:24px; line-height:1.5; margin:0; overflow-wrap:anywhere; font-weight:650; }
@media(max-width:760px) { .blueprint-toolbar { gap:6px; }.view-switch { padding-right:4px; gap:0; button { min-width:30px; padding:5px; } }.toolbar-actions { gap:3px; }.blueprint-selector { flex:1; min-width:40px; max-width:100%; >svg:first-child { display:none; } }.document-heading { font-size:22px; } }
.toolbar-actions :deep(.ant-btn-primary:not(:disabled)), .save-tools :deep(.ant-btn-primary:not(:disabled)) { color:#fff; }
</style>
