<template>
  <a-modal :open="open" class="project-settings-modal" :width="900" :footer="null" :closable="false" @cancel="emit('update:open', false)">
    <template #title>
      <div class="settings-titlebar">
        <span>项目设置</span>
        <div class="settings-actions">
          <a-button size="small" @click="emit('update:open', false)">关闭</a-button>
          <a-button v-if="data && tab !== 'resources'" size="small" type="primary" :loading="saving" @click="save">保存</a-button>
        </div>
      </div>
    </template>
    <div class="settings-layout">
      <aside class="settings-sidebar" aria-label="项目设置分类">
        <button v-for="item in sections" :key="item.key" type="button" class="settings-nav-item" :class="{ active: tab === item.key }" :aria-current="tab === item.key ? 'page' : undefined" @click="tab = item.key">
          <component :is="item.icon" :size="16" />
          <span>{{ item.label }}</span>
        </button>
      </aside>
      <div class="settings-main">
        <h2 class="settings-heading">{{ sections.find((item) => item.key === tab)?.label }}</h2>
        <a-spin :spinning="loading">
          <a-alert v-if="error" type="error" show-icon :message="error" class="settings-alert" />
          <a-button v-if="!data && !loading" @click="load">重新加载</a-button>
          <div v-if="data">
            <section v-show="tab === 'attributes'">
              <a-form layout="horizontal" class="attributes-form" :colon="false" label-align="left">
                <a-form-item label="状态">
                  <a-select v-model:value="draft.work_status" :options="statuses" />
                </a-form-item>
                <a-form-item label="优先级">
                  <a-select v-model:value="draft.priority" :options="priorities" />
                </a-form-item>
                <a-form-item label="负责人">
                  <a-select class="owner-field" v-model:value="ownerSelection" show-search option-filter-prop="label" :options="ownerOptions" placeholder="指派负责人…" popup-class-name="project-owner-dropdown" :dropdown-match-select-width="360" :list-height="320" :list-item-height="44">
                    <template #optionLabel="option">
                      <span class="owner-selected">
                        <span v-if="draft.owner_type === 'none'" class="owner-empty"><UserRoundMinus :size="16" /></span>
                        <FallbackAvatar v-else :src="selectedOwner?.avatar || selectedOwner?.icon || ''" :default-src="selectedOwner?.id ? generatePixelAvatar(selectedOwner.id) : ''" :name="selectedOwner?.name || ''" :seed="draft.owner_id || ''" :kind="draft.owner_type === 'agent' ? 'agent' : 'user'" :shape="draft.owner_type === 'agent' ? 'rounded' : 'circle'" :size="24" decorative />
                        <span class="owner-option-name">{{ option.label }}</span>
                      </span>
                    </template>
                      <template #option="option">
                        <span v-if="option.value !== undefined" class="owner-option">
                          <span v-if="option.ownerType === 'none'" class="owner-option-empty"><UserRoundMinus :size="18" /></span>
                          <FallbackAvatar v-else :src="option.avatar || ''" :default-src="generatePixelAvatar(option.id)" :name="option.label" :seed="option.id" :kind="option.ownerType === 'agent' ? 'agent' : 'user'" :shape="option.ownerType === 'agent' ? 'rounded' : 'circle'" :size="28" decorative />
                          <span class="owner-option-name">{{ option.label }}</span>
                        </span>
                        <span v-else>{{ option.label }}</span>
                      </template>
                  </a-select>
                </a-form-item>
                <a-form-item label="开始日期">
                  <a-date-picker v-model:value="draft.start_date" value-format="YYYY-MM-DD" />
                </a-form-item>
                <a-form-item :label="draft.project_type === 'delivery' ? '交付日期' : '截止日期'">
                  <a-date-picker v-model:value="draft.due_date" value-format="YYYY-MM-DD" />
                </a-form-item>
                <p class="settings-help">负责人仅记录责任归属；项目状态不限制任务执行。</p>
              </a-form>
            </section>
            <section v-show="tab === 'description'">
              <a-form layout="vertical">
                <a-form-item label="项目名称" required>
                  <a-input v-model:value="draft.name" :maxlength="255" />
                </a-form-item>
                <a-form-item label="项目描述">
                  <a-textarea v-model:value="draft.description" :maxlength="255" show-count :rows="5" />
                </a-form-item>
                <a-form-item label="项目类型">
                  <a-select v-model:value="draft.project_type" :options="projectTypes" />
                </a-form-item>
                <a-form-item label="分类（可选）">
                  <a-input v-model:value="draft.category" :maxlength="50" placeholder="例如产品、运营" />
                </a-form-item>
                <a-form-item label="标签（可选）">
                  <a-select v-model:value="draft.tags" mode="tags" :token-separators="[',', '，']" placeholder="输入标签后按回车" />
                  <p class="settings-help">最多 20 个标签，每个最多 30 字符；分类和标签只用于整理与筛选。</p>
                </a-form-item>
              </a-form>
            </section>
            <section v-show="tab === 'resources'">
              <section class="resource-module">
                <h3 class="resource-heading">Git 资源</h3>
                <ProjectGitSettingsModal :open="open && tab === 'resources'" :project="data.project" embedded />
              </section>
              <section class="resource-module">
                <h3 class="resource-heading">知识库</h3>
                <p class="settings-help">关联提供配置选项，不授予读取权限，也不会自动加入每次运行。</p>
                <a-select v-model:value="selectedKnowledge" mode="multiple" show-search option-filter-prop="label" :options="knowledgeOptions" placeholder="选择关联知识库" class="knowledge-select" />
                <div v-for="link in data.knowledge_links.filter((item) => !item.accessible)" :key="link.kb_id" class="settings-help">
                  已关联知识库不可访问或已删除，可从选择框解除关联。
                </div>
                <a-button :loading="savingLinks" @click="saveLinks">保存知识库关联</a-button>
              </section>
            </section>
          </div>
        </a-spin>
      </div>
    </div>
  </a-modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { SlidersHorizontal, FileText, FolderGit2, UserRoundMinus } from '@lucide/vue'
import { projectApi } from '@/apis/project_api'
import ProjectGitSettingsModal from './ProjectGitSettingsModal.vue'
import FallbackAvatar from './common/FallbackAvatar.vue'
import { generatePixelAvatar } from '@/utils/pixelAvatar'
import { projectTypes } from '@/utils/projectSelection'

const props = defineProps({ open: Boolean, project: { type: Object, default: null } })
const emit = defineEmits(['update:open', 'saved'])
const sections = [
  { key: 'attributes', label: '属性', icon: SlidersHorizontal },
  { key: 'description', label: '名称与描述', icon: FileText },
  { key: 'resources', label: '资源', icon: FolderGit2 }
]
const tab = ref('attributes')
const data = ref(null)
const draft = reactive({})
const loading = ref(false)
const saving = ref(false)
const savingLinks = ref(false)
const selectedKnowledge = ref([])
const error = ref('')
let loadVersion = 0
const statuses = [ ['planned', '计划中'], ['in_progress', '进行中'], ['paused', '已暂停'], ['completed', '已完成'], ['cancelled', '已取消'] ].map(([value, label]) => ({ value, label }))
const priorities = [ ['urgent', '紧急'], ['high', '高'], ['medium', '中'], ['low', '低'], ['none', '无优先级'] ].map(([value, label]) => ({ value, label }))
const ownerOptions = computed(() => [
  { value: JSON.stringify(['none', null]), label: '无负责人', ownerType: 'none' },
  ...[['member', '成员', data.value?.members], ['agent', '智能体', data.value?.agents]].map(([type, label, items]) => ({
    label,
    options: (items || []).map((item) => ({ value: JSON.stringify([type, item.id]), label: item.name, ownerType: type, id: item.id, avatar: item.avatar || item.icon }))
  }))
])
const selectedOwner = computed(() => {
  const items = draft.owner_type === 'member' ? data.value?.members : data.value?.agents
  return items?.find((item) => item.id === draft.owner_id)
})
const ownerSelection = computed({
  get: () => draft.owner_type === 'none' || draft.owner_id ? JSON.stringify([draft.owner_type, draft.owner_id]) : undefined,
  set: (value) => { [draft.owner_type, draft.owner_id] = JSON.parse(value) }
})
const knowledgeOptions = computed(() => [
  ...(data.value?.knowledge_candidates || []).map((item) => ({ value: item.kb_id, label: item.name })),
  ...(data.value?.knowledge_links || []).filter((item) => !item.accessible).map((item) => ({ value: item.kb_id, label: '不可访问的已关联知识库' }))
])

/** 只让当前打开的项目请求更新表单。 */
const load = async () => {
  const version = ++loadVersion
  const projectId = props.project?.id
  if (!props.open || !projectId) return
  loading.value = true
  data.value = null
  error.value = ''
  try {
    const result = await projectApi.getSettings(projectId)
    if (version !== loadVersion) return
    data.value = result
    Object.assign(draft, { project_type: 'unspecified', category: null, tags: [] }, result.settings, { name: result.project.name })
    selectedKnowledge.value = result.knowledge_links.map((item) => item.kb_id)
  } catch (err) {
    if (version === loadVersion) error.value = err.message || '项目设置加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

/** 保存同一项目的完整管理属性并使用后端结果刷新。 */
const save = async () => {
  if (!draft.name?.trim()) { error.value = '项目名称不能为空'; return }
  if (draft.owner_type !== 'none' && !draft.owner_id) { error.value = '请选择负责人'; return }
  if (draft.start_date && draft.due_date && draft.start_date > draft.due_date) { error.value = '截止日期不得早于开始日期'; return }
  saving.value = true
  error.value = ''
  const projectId = props.project.id
  const version = loadVersion
  try {
    const result = await projectApi.saveSettings(projectId, { ...draft, owner_id: draft.owner_type === 'none' ? null : draft.owner_id, start_date: draft.start_date || null, due_date: draft.due_date || null })
    emit('saved', result.project)
    if (version === loadVersion) { data.value = result; message.success('项目设置已保存') }
  } catch (err) { if (version === loadVersion) error.value = err.message || '保存失败' }
  finally { saving.value = false }
}

/** 独立保存弱关联，不覆盖尚未保存的属性草稿。 */
const saveLinks = async () => {
  savingLinks.value = true
  error.value = ''
  const version = loadVersion
  try {
    const result = await projectApi.saveKnowledgeLinks(props.project.id, selectedKnowledge.value)
    if (version === loadVersion) { data.value = result; message.success('知识库关联已保存') }
  } catch (err) { if (version === loadVersion) error.value = err.message || '关联保存失败' }
  finally { savingLinks.value = false }
}
watch(() => [props.open, props.project?.id], () => {
  ++loadVersion
  if (props.open) { tab.value = 'attributes'; load() }
}, { immediate: true })
</script>

<style lang="less" scoped>
.settings-titlebar { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.settings-actions { display: flex; gap: 8px; }
.settings-layout { display: grid; grid-template-columns: 144px minmax(0, 1fr); height: min(72vh, 640px); overflow: hidden; background: var(--gray-0); }
.settings-sidebar { display: flex; flex-direction: column; gap: 4px; padding: 14px 10px; overflow-y: auto; border-right: 1px solid var(--gray-150); }
.settings-nav-item {
  display: flex; align-items: center; gap: 8px; width: 100%; min-height: 34px; padding: 6px 9px;
  border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--gray-800);
  font-size: 13px; font-weight: 500; text-align: left; cursor: pointer;
  svg { flex-shrink: 0; color: var(--gray-600); }
  &:hover { background: var(--gray-50); }
  &.active { background: var(--gray-100); color: var(--gray-900); font-weight: 600; }
  &:focus-visible { outline: 2px solid var(--main-color); outline-offset: 1px; }
}
.settings-main { min-width: 0; min-height: 0; overflow: hidden auto; overscroll-behavior: contain; padding: 22px 24px 24px; scrollbar-gutter: stable; }
.settings-heading { margin: 0 0 20px; color: var(--gray-900); font-size: 16px; font-weight: 600; }
.attributes-form {
  :deep(.ant-form-item) { margin-bottom: 18px; }
  :deep(.ant-form-item-row) { flex-wrap: nowrap; align-items: center; }
  :deep(.ant-form-item-label) { flex: 0 0 104px; padding: 0; }
  :deep(.ant-form-item-label > label) { color: var(--gray-600); }
  :deep(.ant-form-item-control) { flex: 0 1 300px; min-width: 0; }
  :deep(.ant-select-selector), :deep(.ant-picker) { border-radius: 6px; }
  :deep(.ant-select-selector:hover), :deep(.ant-picker:hover) { background: var(--gray-50); }
  :deep(.ant-picker) { width: 100%; }
}
.owner-field { width: 100%; }
.owner-selected { display: flex; align-items: center; gap: 8px; height: 100%; min-width: 0; }
.owner-empty { display: inline-flex; align-items: center; justify-content: center; width: 24px; color: var(--gray-600); }
.owner-option { display: flex; align-items: center; gap: 10px; min-width: 0; width: 100%; }
.owner-option-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.owner-option-empty { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; flex-shrink: 0; border-radius: 50%; background: var(--gray-100); color: var(--gray-600); }
:global(.project-owner-dropdown) { padding: 8px; border-radius: 10px; max-width: calc(100vw - 32px); }
:global(.project-owner-dropdown .ant-select-item-option) { display: flex; align-items: center; min-height: 44px; padding: 8px 10px; border-radius: 6px; font-size: 14px; }
:global(.project-owner-dropdown .ant-select-item-option-content) { min-width: 0; }
:global(.project-owner-dropdown .ant-select-item-group) { min-height: 32px; padding: 10px 10px 4px; color: var(--gray-600); font-size: 12px; font-weight: 600; }
:global(.project-owner-dropdown .ant-select-item-option-selected:not(.ant-select-item-option-disabled)) { background: var(--gray-100); color: var(--gray-900); font-weight: 500; }
:global(.project-owner-dropdown .ant-select-item-option-active:not(.ant-select-item-option-selected)) { background: var(--gray-50); }
.resource-module + .resource-module { margin-top: 28px; padding-top: 24px; border-top: 1px solid var(--gray-150); }
.resource-heading { margin: 0 0 16px; color: var(--gray-900); font-size: 14px; font-weight: 600; }
.settings-help { color: var(--color-text-secondary); margin: 12px 0; }
.settings-alert { margin-bottom: 16px; }
.knowledge-select { width: 100%; margin-bottom: 16px; }
:global(.project-settings-modal .ant-modal-content) { padding: 0; overflow: hidden; border-radius: 12px; }
:global(.project-settings-modal .ant-modal-header) { margin: 0; padding: 18px 24px; border-bottom: 1px solid var(--gray-150); background: var(--gray-0); }
:global(.project-settings-modal .ant-modal-body) { padding: 0; }
@media (max-width: 600px) {
  .settings-layout { grid-template-columns: 120px minmax(0, 1fr); }
  .settings-sidebar { padding: 12px 6px; }
  .settings-nav-item { padding: 6px; gap: 6px; }
  .settings-main { padding: 18px 12px; }
  .attributes-form :deep(.ant-form-item-label) { flex-basis: 76px; }
}
</style>
