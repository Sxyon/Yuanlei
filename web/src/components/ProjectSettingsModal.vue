<template>
  <a-modal :open="open" title="项目设置" width="900px" :footer="null" @cancel="emit('update:open', false)">
    <a-spin :spinning="loading">
      <a-alert v-if="error" type="error" show-icon :message="error" class="settings-alert" />
      <a-button v-if="!data && !loading" @click="load">重新加载</a-button>
      <a-tabs v-if="data" v-model:active-key="tab">
        <a-tab-pane key="attributes" tab="属性">
          <a-form layout="vertical">
            <div class="settings-grid">
              <a-form-item label="状态">
                <a-select v-model:value="draft.work_status" :options="statuses" />
              </a-form-item>
              <a-form-item label="优先级">
                <a-select v-model:value="draft.priority" :options="priorities" />
              </a-form-item>
              <a-form-item label="负责人类型">
                <a-select v-model:value="draft.owner_type" :options="ownerTypes" @change="draft.owner_id = null" />
              </a-form-item>
              <a-form-item v-if="draft.owner_type !== 'none'" label="负责人">
                <a-select v-model:value="draft.owner_id" show-search option-filter-prop="label" :options="ownerOptions" placeholder="选择负责人" />
              </a-form-item>
              <a-form-item label="开始日期">
                <a-date-picker v-model:value="draft.start_date" value-format="YYYY-MM-DD" />
              </a-form-item>
              <a-form-item label="截止日期">
                <a-date-picker v-model:value="draft.due_date" value-format="YYYY-MM-DD" />
              </a-form-item>
            </div>
            <p class="settings-help">负责人仅记录责任归属；项目状态不限制任务执行。</p>
          </a-form>
        </a-tab-pane>
        <a-tab-pane key="description" tab="名称与描述">
          <a-form layout="vertical">
            <a-form-item label="项目名称" required>
              <a-input v-model:value="draft.name" :maxlength="255" />
            </a-form-item>
            <a-form-item label="项目描述">
              <a-textarea v-model:value="draft.description" :maxlength="255" show-count :rows="5" />
            </a-form-item>
          </a-form>
        </a-tab-pane>
        <a-tab-pane key="resources" tab="资源">
          <a-tabs>
            <a-tab-pane key="git" tab="Git 资源">
              <ProjectGitSettingsModal :open="open" :project="data.project" embedded />
            </a-tab-pane>
            <a-tab-pane key="knowledge" tab="知识库">
              <p class="settings-help">关联提供配置选项，不授予读取权限，也不会自动加入每次运行。</p>
              <a-select v-model:value="selectedKnowledge" mode="multiple" show-search option-filter-prop="label" :options="knowledgeOptions" placeholder="选择关联知识库" class="knowledge-select" />
              <div v-for="link in data.knowledge_links.filter((item) => !item.accessible)" :key="link.kb_id" class="settings-help">
                已关联知识库不可访问或已删除，可从选择框解除关联。
              </div>
              <a-button :loading="savingLinks" @click="saveLinks">保存知识库关联</a-button>
            </a-tab-pane>
          </a-tabs>
        </a-tab-pane>
      </a-tabs>
      <div v-if="data && tab !== 'resources'" class="settings-actions">
        <a-button @click="emit('update:open', false)">取消</a-button>
        <a-button type="primary" :loading="saving" @click="save">保存属性、名称与描述</a-button>
      </div>
    </a-spin>
  </a-modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { projectApi } from '@/apis/project_api'
import ProjectGitSettingsModal from './ProjectGitSettingsModal.vue'

const props = defineProps({ open: Boolean, project: { type: Object, default: null } })
const emit = defineEmits(['update:open', 'saved'])
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
const ownerTypes = [ { value: 'none', label: '无负责人' }, { value: 'member', label: '成员' }, { value: 'agent', label: '智能体' } ]
const ownerOptions = computed(() => (draft.owner_type === 'member' ? data.value?.members : data.value?.agents)?.map((item) => ({ value: item.id, label: item.name })) || [])
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
    Object.assign(draft, result.settings, { name: result.project.name })
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

<style scoped>
.settings-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 20px; }
.settings-grid :deep(.ant-picker) { width: 100%; }
.settings-help { color: var(--color-text-secondary); margin: 12px 0; }
.settings-actions { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
.settings-alert { margin-bottom: 16px; }
.knowledge-select { width: 100%; margin-bottom: 16px; }
@media (max-width: 600px) { .settings-grid { grid-template-columns: 1fr; } }
</style>
