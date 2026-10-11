<script setup>
import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { Modal, message } from 'ant-design-vue'
import { projectApi } from '@/apis/project_api'
import { useUserStore } from '@/stores/user'
import WorkspacePathPicker from './WorkspacePathPicker.vue'
import ProjectIdentityFields from './ProjectIdentityFields.vue'
import { fillProjectNameFromFolder, projectTypes } from '@/utils/projectSelection'
import { projectStatuses, projectPriorities } from '@/utils/projectManagement'

const props = defineProps({ open: Boolean, initialPath: { type: String, default: '' }, selectAfterCreate: Boolean })
const emit = defineEmits(['update:open', 'created'])
const user = useUserStore()
const draft = reactive({})
const saving = ref(false), uploading = ref(false), loading = ref(false), error = ref('')
const members = ref([]), scopeKey = ref('')
let version = 0, initial = '', submitted = '', requestId = ''
const owner = computed({
  get: () => draft.attributes?.owner_type === 'none' ? '' : draft.attributes?.owner_id,
  set: (value) => { draft.attributes.owner_type = value ? 'member' : 'none'; draft.attributes.owner_id = value || null }
})
const ownerOptions = computed(() => [{ value: '', label: '无负责人' }, ...members.value.map(m => ({value: m.id, label: m.name}))])
const canCreate = computed(() => Boolean(draft.name?.trim() && draft.path && !saving.value && !uploading.value && !loading.value && members.value.length))

/** 读取现有成员候选，关闭弹窗后丢弃迟到响应。 */
async function loadMembers() {
  const current = ++version
  loading.value = true
  error.value = ''
  try {
    const result = await projectApi.getCreationOptions()
    if (current === version) members.value = result.members
  } catch (err) { if (current === version) error.value = err.message || '负责人候选加载失败' }
  finally { if (current === version) loading.value = false }
}
/** 未保存输入在关闭前由用户决定是否舍弃。 */
function close() {
  if (saving.value || uploading.value) return
  const leave = () => emit('update:open', false)
  if (JSON.stringify(draft) !== initial) Modal.confirm({ title: '放弃未保存的项目？', content: '已新建的文件夹会保留，可再次选择。', okText: '放弃', cancelText: '继续编辑', onOk: leave })
  else leave()
}
/** 完整创建意图一次提交，失败保留输入并安全重试。 */
async function create() {
  if (!canCreate.value) return
  if (draft.slug && !/^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/.test(draft.slug.trim())) { error.value = '项目标识需为 1—64 位字母、数字或连字符，首尾为字母或数字'; return }
  if (draft.attributes.start_date && draft.attributes.due_date && draft.attributes.start_date > draft.attributes.due_date) { error.value = '截止日期不得早于开始日期'; return }
  const payload = { name: draft.name.trim(), mode: 'linked', path: draft.path, icon: draft.icon, slug: draft.slug, attributes: { ...draft.attributes } }
  const intent = JSON.stringify(payload)
  if (intent !== submitted) { requestId = crypto.randomUUID(); submitted = intent }
  saving.value = true; error.value = ''
  try {
    const project = await projectApi.createProject({ ...payload, requestId })
    emit('created', project); emit('update:open', false)
    message.success('项目已创建')
  } catch (err) { error.value = err.message || '项目创建失败' }
  finally { saving.value = false }
}
watch(() => props.open, (open) => {
  ++version
  if (!open) return
  scopeKey.value = crypto.randomUUID(); uploading.value = false; members.value = []; submitted = ''
  Object.assign(draft, {name: '', path: props.initialPath, icon: null, slug: null, attributes: {description: '', project_type: 'unspecified', category: null, tags: [], work_status: 'planned', priority: 'none', owner_type: 'member', owner_id: user.uid, start_date: null, due_date: null}})
  initial = JSON.stringify(draft)
  void loadMembers()
}, {immediate: true})
onUnmounted(() => ++version)
</script>

<template>
  <a-modal :open="open" title="新建项目" :width="760" :confirm-loading="saving" :ok-text="selectAfterCreate ? '创建并选择' : '创建项目'" cancel-text="取消" :ok-button-props="{disabled: !canCreate}" :cancel-button-props="{disabled: saving || uploading}" :closable="!saving && !uploading" :mask-closable="false" @ok="create" @cancel="close">
    <div v-if="open" class="create-form">
      <a-alert v-if="error" type="error" show-icon :message="error" />
      <a-button v-if="!loading && !members.length" @click="loadMembers">重新读取负责人候选</a-button>
      <a-form layout="vertical" :disabled="saving">
        <a-form-item label="项目名称" required><a-input v-model:value="draft.name" :maxlength="255" placeholder="例如：产品发布计划" autofocus /></a-form-item>
        <ProjectIdentityFields v-model:icon="draft.icon" v-model:slug="draft.slug" :scope-key="scopeKey" :disabled="saving" @uploading="uploading = $event" />
        <a-form-item label="项目描述"><a-textarea v-model:value="draft.attributes.description" :maxlength="255" show-count :rows="3" /></a-form-item>
        <a-form-item label="项目目录（Workdir）" required>
          <WorkspacePathPicker v-model="draft.path" :active="open" :disabled="saving" :suggested-folder-name="draft.name" include-unbound-project-dirs @folder-created="draft.name = fillProjectNameFromFolder(draft.name, $event.name)" />
          <p class="help">沿用个人空间内的目录；新建文件夹与保存项目分别执行，创建失败后文件夹仍保留。</p>
        </a-form-item>
        <div class="form-grid">
          <a-form-item label="项目类型"><a-select v-model:value="draft.attributes.project_type" :options="projectTypes" /></a-form-item>
          <a-form-item label="分类（可选）"><a-input v-model:value="draft.attributes.category" :maxlength="50" /></a-form-item>
        </div>
        <a-form-item label="标签（可选）"><a-select v-model:value="draft.attributes.tags" mode="tags" :token-separators="[',', '，']" placeholder="输入标签后按回车" /><p class="help">最多 20 个，每个最多 30 字符。</p></a-form-item>
        <details><summary>更多管理属性</summary>
          <div class="form-grid">
            <a-form-item label="管理状态"><a-select v-model:value="draft.attributes.work_status" :options="projectStatuses" /></a-form-item>
            <a-form-item label="优先级"><a-select v-model:value="draft.attributes.priority" :options="projectPriorities" /></a-form-item>
            <a-form-item label="负责人"><a-select v-model:value="owner" :loading="loading" :options="ownerOptions" show-search option-filter-prop="label" /></a-form-item>
            <a-form-item label="账号归属"><a-input :value="user.username" readonly /></a-form-item>
            <a-form-item label="开始日期"><a-date-picker v-model:value="draft.attributes.start_date" value-format="YYYY-MM-DD" /></a-form-item>
            <a-form-item :label="draft.attributes.project_type === 'delivery' ? '交付日期' : '截止日期'"><a-date-picker v-model:value="draft.attributes.due_date" value-format="YYYY-MM-DD" /></a-form-item>
          </div>
          <p class="help">负责人仅记录责任归属；管理状态不限制任务执行。新项目尚未绑定智能体。</p>
        </details>
      </a-form>
    </div>
  </a-modal>
</template>

<style scoped lang="less">
.create-form { max-height: 70vh; overflow-y: auto; padding: 4px 8px 4px 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; :deep(.ant-picker) { width: 100%; } }
.help { font-size: 12px; color: var(--color-text-secondary); margin: 8px 0; line-height: 1.7; }
summary { cursor: pointer; margin-bottom: 18px; font-weight: 500; }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; } }
</style>
