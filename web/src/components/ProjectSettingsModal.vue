<template>
  <component :is="embedded ? 'section' : 'a-modal'" :open="open" class="project-settings-modal" :class="{ 'embedded-settings': embedded }" :width="900" :footer="null" :closable="false" @cancel="close">
    <template v-if="!embedded" #title>
      <div class="settings-titlebar">
        <span>项目设置</span>
        <div class="settings-actions">
          <a-button size="small" :disabled="saving || savingLinks || iconUploading" @click="close">关闭</a-button>
          <a-button v-if="data && tab !== 'resources'" size="small" type="primary" :loading="saving" :disabled="iconUploading" @click="save">保存</a-button>
        </div>
      </div>
    </template>
    <div v-if="embedded" class="embedded-settings-tools"><a-button type="primary" :loading="saving" :disabled="savingLinks || iconUploading" @click="save">保存设置</a-button></div>
    <div class="settings-layout">
      <aside v-if="!embedded" class="settings-sidebar" aria-label="项目设置分类">
        <button v-for="item in sections" :key="item.key" type="button" class="settings-nav-item" :class="{ active: tab === item.key }" :aria-current="tab === item.key ? 'page' : undefined" @click="tab = item.key">
          <component :is="item.icon" :size="16" />
          <span>{{ item.label }}</span>
        </button>
      </aside>
      <div class="settings-main">
        <h2 v-if="!embedded" class="settings-heading">{{ embedded ? '基本信息' : sections.find((item) => item.key === tab)?.label }}</h2>
        <a-spin :spinning="loading">
          <a-alert v-if="error" type="error" show-icon :message="error" class="settings-alert" />
          <a-button v-if="!data && !loading" @click="load">重新加载</a-button>
          <div v-if="data" class="project-settings-grid">
            <div class="settings-top"><section v-show="embedded || tab === 'description'" class="project-identity">
              <ProjectIdentityFields v-model:icon="draft.icon" v-model:slug="draft.slug" :slug-locked="Boolean(data.settings.slug)" :scope-key="data.project.id" :name="draft.name" :disabled="saving" @uploading="iconUploading = $event">
                <template v-if="embedded" #name><label for="embedded-project-name" class="sr-only">项目名称</label><a-input id="embedded-project-name" v-model:value="draft.name" aria-label="项目名称" :maxlength="255" :disabled="saving" class="identity-name-input" /></template>
              </ProjectIdentityFields>
              <a-form :disabled="saving" layout="vertical" class="identity-description-form">
                <a-form-item v-if="!embedded" label="项目名称" required>
                  <a-input v-model:value="draft.name" :maxlength="255" />
                </a-form-item>
                <a-form-item :label="embedded ? undefined : '项目描述'">
                  <a-textarea v-model:value="draft.description" aria-label="项目描述" placeholder="添加项目描述，说明这个项目的方向与用途…" :maxlength="255" :show-count="!embedded" :rows="embedded ? 2 : 5" class="identity-description-input" />
                </a-form-item>
              </a-form>
            </section>
            <section v-show="embedded || tab === 'attributes'" class="project-attributes"><h3 v-if="embedded" class="resource-heading planning-heading">属性<a-tooltip title="负责人仅记录责任归属；项目状态不限制任务执行。" :trigger="['hover', 'focus']"><button type="button" class="planning-help" aria-label="项目属性说明"><CircleHelp :size="15" /></button></a-tooltip></h3>
              <a-form :disabled="saving" layout="horizontal" class="attributes-form" :colon="false" label-align="left">
                <div class="status-priority-row">
                <a-form-item label="状态">
                  <a-select v-model:value="draft.work_status" :options="statuses" :bordered="!embedded" :show-arrow="!embedded" aria-label="项目状态"><template v-if="embedded" #optionLabel="option"><span class="property-value"><span class="property-status-dot" :class="`property-status-${draft.work_status}`" />{{ option.label }}</span></template></a-select>
                </a-form-item>
                <a-form-item label="优先级">
                  <a-select v-model:value="draft.priority" :options="priorities" :bordered="!embedded" :show-arrow="!embedded" aria-label="项目优先级"><template v-if="embedded" #optionLabel="option"><span class="property-value"><Minus v-if="draft.priority === 'none'" :size="16" /><Flag v-else :size="14" />{{ option.label }}</span></template></a-select>
                </a-form-item>
                </div>
                <a-form-item label="负责人">
                  <a-select :bordered="!embedded" :show-arrow="!embedded" aria-label="项目负责人" class="owner-field" v-model:value="ownerSelection" show-search option-filter-prop="label" :options="ownerOptions" placeholder="指派负责人…" popup-class-name="project-owner-dropdown" :dropdown-match-select-width="360" :list-height="320" :list-item-height="44">
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
                  <a-date-picker v-model:value="draft.start_date" value-format="YYYY-MM-DD" :bordered="!embedded" placeholder="开始日期" aria-label="项目开始日期" />
                </a-form-item>
                <a-form-item :label="draft.project_type === 'delivery' ? '交付日期' : '截止日期'">
                  <a-date-picker v-model:value="draft.due_date" value-format="YYYY-MM-DD" :bordered="!embedded" :placeholder="draft.project_type === 'delivery' ? '交付日期' : '截止日期'" aria-label="项目截止日期" />
                </a-form-item>
              </a-form>
            </section>
            </div>
            <div class="settings-columns"><div v-if="embedded" class="settings-primary"><ProjectGitWorkspace ref="gitWorkspace" :project-id="data.project.id" /></div><div class="settings-secondary">
            <section v-show="embedded || tab === 'description'" class="project-classification"><a-form :disabled="saving" layout="vertical">
                <a-form-item><template #label>项目目录（Workdir）<a-tooltip title="目录绑定后不可在此换绑；多个项目可共享目录文件。" :trigger="['hover','focus']"><button type="button" class="planning-help" aria-label="项目目录说明"><CircleHelp :size="14" /></button></a-tooltip></template>
                  <p class="settings-readonly">{{ data.project.workdir_path || '尚未绑定' }}</p>
                </a-form-item>
                <a-form-item label="账号归属">
                  <p class="settings-readonly">{{ data.project.uid === user.uid ? user.username : data.project.uid }}</p>
                </a-form-item>
                <a-form-item label="项目类型">
                  <a-select v-model:value="draft.project_type" :options="projectTypes" />
                </a-form-item>
                <a-form-item label="分类（可选）">
                  <a-input v-model:value="draft.category" :maxlength="50" placeholder="例如产品、运营" />
                </a-form-item>
                <a-form-item><template #label>标签<a-tooltip title="最多20个标签，每个30字；分类与标签仅用于整理和筛选。" :trigger="['hover','focus']"><button type="button" class="planning-help" aria-label="项目标签说明"><CircleHelp :size="14" /></button></a-tooltip></template>
                  <a-select v-model:value="draft.tags" mode="tags" :token-separators="[',', '，']" placeholder="输入标签后按回车" />
                </a-form-item>
              </a-form>
            </section>
            <section ref="resourcesSection" v-show="embedded || tab === 'resources'" class="project-resources">

              <section class="resource-module">
                <div class="repository-heading"><h3 class="resource-heading">仓库</h3><a-button v-if="embedded" size="small" @click="repositorySettings?.refresh()">刷新配置</a-button></div>
                <ProjectGitSettingsModal ref="repositorySettings" :open="open && (embedded || tab === 'resources')" :project="data.project" :section="embedded ? 'repositories' : 'all'" :auto-refresh="!embedded" embedded @updated="gitWorkspace?.refresh()" />
              </section>
              <section class="resource-module">
                <h3 class="resource-heading planning-heading">知识库<a-tooltip title="关联提供配置选项，不授予读取权限，也不会自动加入每次运行。" :trigger="['hover','focus']"><button type="button" class="planning-help" aria-label="知识库关联说明"><CircleHelp :size="15" /></button></a-tooltip></h3>
                <a-select v-model:value="selectedKnowledge" mode="multiple" show-search option-filter-prop="label" :options="knowledgeOptions" placeholder="选择关联知识库" class="knowledge-select" />
                <div v-for="link in data.knowledge_links.filter((item) => !item.accessible)" :key="link.kb_id" class="settings-help">
                  已关联知识库不可访问或已删除，可从选择框解除关联。
                </div>
                <a-button :loading="savingLinks" @click="saveLinks">保存知识库关联</a-button>
              </section>
            </section>
            <div v-if="embedded" class="project-settings-aside"><slot name="project-aside" /></div>
            </div></div>
          </div>
        </a-spin>
      </div>
    </div>
  </component>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, nextTick, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Modal, message } from 'ant-design-vue'
import { SlidersHorizontal, FileText, FolderGit2, UserRoundMinus, CircleHelp, Minus, Flag } from '@lucide/vue'
import { projectApi } from '@/apis/project_api'
import ProjectGitSettingsModal from './ProjectGitSettingsModal.vue'
import ProjectGitWorkspace from './ProjectGitWorkspace.vue'
import ProjectIdentityFields from './ProjectIdentityFields.vue'
import FallbackAvatar from './common/FallbackAvatar.vue'
import { generatePixelAvatar } from '@/utils/pixelAvatar'
import { projectTypes } from '@/utils/projectSelection'
import { useUserStore } from '@/stores/user'
import { projectStatuses, projectPriorities } from '@/utils/projectManagement'

const props = defineProps({ open: Boolean, embedded: Boolean, project: { type: Object, default: null }, initialTab: { type: String, default: 'attributes' } })
const emit = defineEmits(['update:open', 'saved'])
const sections = [
  { key: 'attributes', label: '属性', icon: SlidersHorizontal },
  { key: 'description', label: '名称与描述', icon: FileText },
  { key: 'resources', label: '资源', icon: FolderGit2 }
]
const gitWorkspace = ref(null), repositorySettings = ref(null)
const user = useUserStore()
const tab = ref(props.initialTab), resourcesSection = ref(null)
defineExpose({ openResources: async () => { tab.value = 'resources'; await nextTick(); resourcesSection.value?.scrollIntoView({ block: 'start' }) } })
const data = ref(null)
const draft = reactive({})
const loading = ref(false)
const saving = ref(false)
const iconUploading = ref(false)
const savingLinks = ref(false)
const selectedKnowledge = ref([])
const error = ref('')
let loadVersion = 0
const statuses = projectStatuses
const priorities = projectPriorities
let savedDraft = '', savedKnowledge = ''
const settingsDirty = computed(() => data.value && (JSON.stringify(draft) !== savedDraft || JSON.stringify(selectedKnowledge.value) !== savedKnowledge))
if (props.embedded) onBeforeRouteLeave(() => {
  if (saving.value || savingLinks.value || iconUploading.value) return false
  if (!settingsDirty.value) return true
  return new Promise(resolve => Modal.confirm({ title:'放弃未保存的项目设置？',okText:'放弃并离开',cancelText:'继续编辑',onOk:()=>resolve(true),onCancel:()=>resolve(false) }))
})
function beforeUnload(event) { if(props.embedded && settingsDirty.value) {event.preventDefault();event.returnValue=''} }
onMounted(()=>{ if(props.embedded) window.addEventListener('beforeunload',beforeUnload) })
onBeforeUnmount(()=>{loadVersion++;if(props.embedded) window.removeEventListener('beforeunload',beforeUnload)})
/** 保护管理属性和资源选择的未保存输入。 */
function close() {
  if (saving.value || savingLinks.value || iconUploading.value) return
  const leave = () => emit('update:open', false)
  if (data.value && (JSON.stringify(draft) !== savedDraft || JSON.stringify(selectedKnowledge.value) !== savedKnowledge)) {
    Modal.confirm({ title: '放弃未保存的项目设置？', okText: '放弃', cancelText: '继续编辑', onOk: leave })
  } else leave()
}
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
  iconUploading.value = false
  error.value = ''
  try {
    const result = await projectApi.getSettings(projectId)
    if (version !== loadVersion) return
    data.value = result
    Object.assign(draft, { icon: '', slug: '', project_type: 'unspecified', category: null, tags: [] }, result.settings, { name: result.project.name })
    selectedKnowledge.value = result.knowledge_links.map((item) => item.kb_id)
    savedDraft = JSON.stringify(draft); savedKnowledge = JSON.stringify(selectedKnowledge.value)
  } catch (err) {
    if (version === loadVersion) error.value = err.message || '项目设置加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

/** 保存同一项目的完整管理属性并使用后端结果刷新。 */
const save = async () => {
  if (saving.value || iconUploading.value) return
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
    if (version === loadVersion) { data.value = result; Object.assign(draft, result.settings, { name: result.project.name }); savedDraft = JSON.stringify(draft); message.success('项目设置已保存') }
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
    if (version === loadVersion) { data.value = result; savedKnowledge = JSON.stringify(selectedKnowledge.value); message.success('知识库关联已保存') }
  } catch (err) { if (version === loadVersion) error.value = err.message || '关联保存失败' }
  finally { savingLinks.value = false }
}
watch(() => [props.open, props.project?.id], () => {
  ++loadVersion
  if (props.open) { tab.value = props.initialTab; load() }
}, { immediate: true })
</script>

<style scoped lang="less">
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
  .settings-layout { grid-template-columns: minmax(0, 1fr); height: min(78vh, 720px); }
  .settings-sidebar { flex-direction: row; flex-shrink: 0; border-right: 0; border-bottom: 1px solid var(--gray-150); }
  .settings-nav-item { width: auto; white-space: nowrap; }
  .settings-sidebar { padding: 12px 6px; }
  .settings-nav-item { padding: 6px; gap: 6px; }
  .settings-main { padding: 18px 12px; }
  .attributes-form :deep(.ant-form-item-label) { flex-basis: 76px; }
}

.planning-heading { display:flex; align-items:center; gap:6px; }
.planning-help { display:inline-flex; align-items:center; justify-content:center; border:0; border-radius:4px; background:transparent; color:var(--color-text-secondary); padding:4px; cursor:help; &:focus-visible { outline:2px solid var(--main-color); outline-offset:2px; } }
.status-priority-row { display:contents; }
.embedded-settings-tools { display:flex; justify-content:flex-end; margin-bottom:16px; }

/* 项目设置由独立业务卡片组合，弹窗入口仍保留自己的导航与滚动。 */
.settings-readonly { margin:0; line-height:1.8; color:var(--color-text-secondary); overflow-wrap:anywhere; }
.sr-only { position:absolute; width:1px; height:1px; overflow:hidden; clip:rect(0,0,0,0); }
.embedded-settings {
  max-width:1440px; margin:0 auto;
  .settings-layout { display:block; height:auto; overflow:visible; background:transparent; }
  .settings-main { overflow:visible; scrollbar-gutter:auto; padding:0; background:transparent; border:0; }
  .project-settings-grid { display:block; }
  .settings-top,.settings-columns { display:grid; grid-template-columns:minmax(0,1fr) minmax(280px,340px); gap:24px; align-items:start; }
  .settings-top { align-items:stretch; margin-bottom:24px; }
  .settings-primary,.settings-secondary { min-width:0; }
  .settings-secondary { display:grid; gap:20px; }
  .embedded-settings-tools { padding:20px 0; min-height:72px; margin:0; }
  .project-identity,.project-classification,.project-attributes,.resource-module { min-width:0; padding:24px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; margin:0; }
  .project-identity { padding:24px; align-self:stretch; display:flex; flex-direction:column; }
  .project-attributes { align-self:stretch; padding:20px; }
  .project-classification { grid-column:1 / -1; }
  .project-classification :deep(.ant-form) { display:block; }
  .project-classification :deep(.ant-form-item:last-child) { grid-column:1 / -1; }
  .status-priority-row { display:contents; }
  .attributes-form :deep(.ant-form-item) { margin-bottom:6px; border-radius:6px; }
  .attributes-form :deep(.ant-form-item:last-child) { margin-bottom:0; }
  .attributes-form :deep(.ant-form-item-row) { min-height:38px; flex-wrap:nowrap; align-items:center; }
  .attributes-form :deep(.ant-form-item-label) { flex:0 0 80px; padding:0; }
  .attributes-form :deep(.ant-form-item-label>label) { font-size:14px; color:var(--color-text-secondary); }
  .attributes-form :deep(.ant-select-selector) { padding:0 8px!important; background:transparent; box-shadow:none!important; }
  .attributes-form :deep(.ant-select-selection-item) { font-size:14px; }
  .attributes-form :deep(.ant-select:hover), .attributes-form :deep(.ant-picker:hover) { background:var(--gray-50); border-radius:6px; }
  .attributes-form :deep(.ant-select-focused), .attributes-form :deep(.ant-picker-focused) { outline:2px solid var(--main-color); outline-offset:1px; border-radius:6px; }
  .attributes-form :deep(.ant-picker) { padding:4px 8px; background:transparent; box-shadow:none; }
  .attributes-form :deep(.ant-picker-suffix) { order:-1; margin:0 8px 0 0; }
  .attributes-form :deep(.ant-picker-input>input) { font-size:14px; }
  .property-value { display:flex; align-items:center; gap:8px; color:var(--color-text); }
  .property-value>svg { color:var(--color-text-secondary); flex-shrink:0; }
  .property-status-dot { width:8px; height:8px; border-radius:50%; background:var(--gray-500); flex-shrink:0; }
  .property-status-in_progress { background:var(--main-color); }.property-status-completed { background:var(--color-success-500); }.property-status-paused { background:var(--color-warning-500); }
  .planning-heading { margin-bottom:14px; }
  .project-identity :deep(.project-identity-fields) { margin:0; }
  .project-identity :deep(.ant-form-item) { margin:0; }
  .identity-name-input { max-width:820px; font-size:22px; font-weight:600; line-height:1.5; padding:2px 8px; margin-left:-8px; border-color:transparent; background:transparent; &:hover { border-color:var(--gray-150); } &:focus { border-color:var(--main-color); } }
  .identity-description-form { margin:18px 0 0; flex:1; min-height:0; display:flex; flex-direction:column; }
  .identity-description-form :deep(.ant-form-item), .identity-description-form :deep(.ant-form-item-row), .identity-description-form :deep(.ant-form-item-control), .identity-description-form :deep(.ant-form-item-control-input), .identity-description-form :deep(.ant-form-item-control-input-content) { flex:1; display:flex; flex-direction:column; align-items:stretch; min-height:0; }
  .identity-description-form :deep(textarea) { flex:1; width:100%; height:100%!important; min-height:72px; resize:none; }
  .identity-description-input { padding:10px 12px; font-size:14px; line-height:1.8; color:var(--color-text-secondary); background:var(--gray-25); border-color:transparent; border-radius:8px; resize:none; &:hover { border-color:var(--gray-150); } &:focus { color:var(--color-text); border-color:var(--main-color); } }
  .resource-heading { font-size:16px; margin:0 0 20px; }
  .project-classification :deep(.ant-form-item:last-child) { margin-bottom:0; }
  .project-resources,.project-settings-aside { display:contents; }
  .repository-heading { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:16px; .resource-heading { margin:0; } }
  .project-resources>.resource-module { width:100%; }
  .project-resources :deep(.form-grid),.project-resources :deep(.resource-grid),.project-resources :deep(.policy-editor),.project-resources :deep(.git-item) { grid-template-columns:minmax(0,1fr); }
  .project-resources>.resource-module:first-child { grid-column:1 / -1; }
  .resource-module+.resource-module { margin:0; }
  .attributes-form :deep(.ant-form-item-control) { flex:1; min-width:0; }
  .settings-main :deep(.ant-form-item-label) { text-align:left; }
  :deep(.settings-aside-stack) { display:contents; }
  :deep(.settings-panel) { min-width:0; padding:24px; border:1px solid var(--gray-150); border-radius:10px; background:var(--gray-0); }
  :deep(.settings-danger) { grid-column:1 / -1; }
}
@media(max-width:1100px) { .embedded-settings .settings-top,.settings-columns { grid-template-columns:minmax(0,1fr); } }
@media(max-width:760px) { .embedded-settings { .settings-top,.settings-columns { grid-template-columns:minmax(0,1fr); gap:18px; }.project-identity,.project-classification,.project-attributes,.resource-module { padding:20px 18px; }.identity-name-input { font-size:19px; }.identity-description-form { margin:18px 0 0; }.project-classification :deep(.ant-form) { grid-template-columns:minmax(0,1fr); }:deep(.settings-panel) { padding:20px 18px; } } }
</style>
