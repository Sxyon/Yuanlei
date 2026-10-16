<template>
  <component
    :is="embedded ? 'div' : 'a-modal'"
    :open="open"
    :title="`${project?.name || '项目'} · Git 仓库`"
    width="840px"
    :footer="null"
    @cancel="emit('update:open', false)"
  >
    <a-alert
      v-if="error"
      class="git-alert"
      type="error"
      show-icon
      :message="error"
      closable
      @close="error = ''"
    />
    <component :is="section === 'all' ? 'a-tabs' : 'div'" v-model:active-key="activeTab">
      <component :is="section === 'all' ? 'a-tab-pane' : 'section'" v-if="section === 'all' || section === 'repositories'" key="repositories" tab="仓库">
        <div v-if="repositories.length" class="section-head">
          <a-button
            type="primary"
            danger
            size="small"
            @click="showRepositoryForm = !showRepositoryForm"
          >
            {{ showRepositoryForm ? '收起' : '添加仓库' }}
          </a-button>
        </div>
        <a-form v-if="!repositories.length || showRepositoryForm" layout="vertical" class="create-form">
          <a-alert v-if="discoveryError" type="error" show-icon :message="discoveryError" />
          <div class="form-grid">
            <a-form-item label="Gitea 连接" required>
              <a-select
                v-model:value="repositoryForm.connection_id"
                placeholder="选择已配置的连接"
              >
                <a-select-option v-for="item in activeConnections" :key="item.id" :value="item.id">
                  {{ item.name }}
                </a-select-option>
              </a-select>
              <a-button v-if="openSettingsModal" type="link" size="small" @click="openSettingsModal('gitConnections')">管理我的 Git 连接</a-button>
              <p v-if="!activeConnections.length && !loading" class="connection-hint">先在系统设置 → Git 连接中添加连接，再绑定项目仓库。</p>
            </a-form-item>
            <a-form-item label="仓库" required>
              <a-select v-model:value="selectedRepositoryId" show-search option-filter-prop="label"
                :loading="loadingRemoteRepositories" :disabled="!repositoryForm.connection_id"
                :options="remoteRepositories.map((item) => ({ value: item.id, label: `${item.owner}/${item.name}` }))"
                placeholder="选择此连接可访问的仓库" @change="selectRemoteRepository" />
              <a-button type="link" size="small" :disabled="!repositoryForm.connection_id || loadingRemoteRepositories" @click="loadRemoteRepositories">刷新仓库列表</a-button>
            </a-form-item>
            <a-form-item label="资源名称" required>
              <a-input v-model:value="repositoryForm.alias" maxlength="80" placeholder="选择仓库后自动填写，可修改" />
            </a-form-item>
            <a-form-item label="仓库用途" required>
              <a-input v-model:value="repositoryForm.purpose" maxlength="500" placeholder="例如 后端 API" />
            </a-form-item>
            <a-form-item label="项目目录">
              <a-input v-model:value="repositoryForm.checkout_path" placeholder="默认与仓库同名；同仓库多分支请使用不同目录" />
            </a-form-item>
            <a-form-item><template #label>使用模式<a-tooltip title="直接修改项目目录时，任务持续占用并排队使用；并行模式使用独立工作树。" :trigger="['hover','focus']"><button type="button" class="policy-help" aria-label="新仓库使用模式说明">?</button></a-tooltip></template>
              <a-select v-model:value="repositoryForm.usage_mode">
                <a-select-option value="in_place">直接修改这个文件夹</a-select-option>
                <a-select-option value="worktree">并行隔离运行</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item><template #label>授权模式<a-tooltip title="受保护目标需人工批准；自动授权和任务分支的批准依据可在历史记录查看。授权模式不会自动触发提交或合并。" :trigger="['hover','focus']"><button type="button" class="policy-help" aria-label="新仓库授权模式说明">?</button></a-tooltip></template>
              <a-select v-model:value="repositoryForm.approval_mode">
                <a-select-option value="protected">受保护</a-select-option>
                <a-select-option value="automatic">自动授权（保留批准记录）</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="检出分支（同时作为任务基线）">
              <a-select v-model:value="repositoryForm.configured_base_branch" show-search
                :loading="loadingRemoteBranches" :disabled="!selectedRepositoryId"
                :options="remoteBranches.map((item) => ({ value: item.name, label: item.name }))"
                placeholder="选择仓库后自动选择远端默认分支" />
            </a-form-item>
            <a-form-item class="full-row" label="允许的任务基线">
              <a-select
                v-model:value="repositoryForm.allowed_base_branches"
                mode="multiple"
                :options="remoteBranches.map((item) => ({ value: item.name, label: item.name }))"
                :loading="loadingRemoteBranches"
                :disabled="!selectedRepositoryId"
                :max-tag-count="4"
                placeholder="留空时仅使用所选检出分支"
              />
            </a-form-item>
          </div>
          <a-button
            type="primary"
            html-type="button"
            :loading="savingRepository"
            :disabled="!canBindRepository"
            @click="createRepository"
            >绑定仓库</a-button
          >
        </a-form>
        <a-spin :spinning="loading">
          <a-empty v-if="!repositories.length" description="尚未绑定仓库" />
          <div v-else class="item-list">
            <article v-for="item in repositories" :key="item.id" class="git-item">
              <div>
                <strong>{{ item.alias }}</strong>
                <span>{{ item.repository_owner }}/{{ item.repository_name }}</span>
                <small>{{ item.purpose || '项目仓库' }}</small>
                <small>
                  远端默认 {{ item.default_branch || '等待读取' }} · 任务基线
                  {{ item.configured_base_branch || '未设置（保存时将取远端默认）' }}
                </small>
              </div>
              <div class="item-actions">
                <a-tag :color="statusColor(item.status)">{{ item.status }}</a-tag>
                <a-button
                  v-if="['provision_failed', 'delete_failed'].includes(item.status)"
                  size="small"
                  @click="retryRepository(item)"
                  >重试</a-button
                >
                <a-popconfirm
                  v-if="item.status !== 'disabled'"
                  title="撤销远端权限并保留本地代码？"
                  @confirm="deactivateRepository(item)"
                >
                  <a-button size="small" danger>停用</a-button>
                </a-popconfirm>
              </div>
              <GitResourcePanel :mode="section === 'repositories' ? 'configure' : 'full'" v-if="['active', 'provision_failed'].includes(item.status)" :project-id="project.id" :resource="item" @updated="load({ quiet: true })" />
              <p v-if="item.last_error_message" class="item-error">{{ item.last_error_message }}</p>
              <div v-if="item.status === 'active' && policyDrafts[item.id]" class="policy-editor">
                <label class="policy-field">
                  <span class="policy-label">
                    仓库用途
                    <a-tooltip title="写给 Agent 看的仓库说明，帮助它在多个仓库中判断这个任务该用哪个仓库，例如「后端 API」「前端官网」。不影响程序逻辑。">
                      <QuestionCircleOutlined class="policy-help" />
                    </a-tooltip>
                  </span>
                  <a-input
                    v-model:value="policyDrafts[item.id].purpose"
                    maxlength="500"
                    aria-label="仓库用途"
                  />
                </label>
                <label class="policy-field">
                  <span class="policy-label">
                    默认任务基线
                    <a-tooltip title="任务不指定基线时默认从哪个分支拉新分支。留空保存时会重置为当时的远端默认分支并固定，之后远端默认分支变化不会跟随。">
                      <QuestionCircleOutlined class="policy-help" />
                    </a-tooltip>
                  </span>
                  <a-input
                    v-model:value="policyDrafts[item.id].configured_base_branch"
                    maxlength="255"
                    aria-label="默认任务基线"
                    :placeholder="`留空保存时重置为远端默认（当前 ${item.default_branch || '读取中'}）`"
                  />
                </label>
                <label class="policy-field policy-field-wide">
                  <span class="policy-label">
                    允许的任务基线
                    <a-tooltip title="任务可选择的基线分支白名单，请求不在名单内会被拒绝；默认任务基线必须包含在名单内。想支持从不同分支拉新分支执行任务，把这些分支都加进名单。留空保存时重置为仅包含默认任务基线。">
                      <QuestionCircleOutlined class="policy-help" />
                    </a-tooltip>
                  </span>
                  <a-select
                    v-model:value="policyDrafts[item.id].allowed_base_branches"
                    mode="tags"
                    :max-tag-count="6"
                    aria-label="允许的任务基线"
                    placeholder="可拉新分支的基线白名单"
                  />
                </label>
                <div class="policy-actions">
                  <a-button
                    v-if="isPolicyDirty(item.id)"
                    size="small"
                    @click="restorePolicy(item)"
                  >恢复</a-button>
                  <a-button
                    size="small"
                    type="primary"
                    :loading="savingPolicyId === item.id"
                    @click="savePolicy(item)"
                  >保存策略</a-button>
                </div>
              </div>
            </article>
          </div>
        </a-spin>
      </component>

      <component :is="section === 'all' ? 'a-tab-pane' : 'section'" v-if="section === 'all' || section === 'worktrees'" key="worktrees" tab="Worktrees">
        <a-spin :spinning="loading">
          <a-empty v-if="!worktrees.length" description="根任务首次运行后会在这里显示 worktree" />
          <div v-else class="item-list">
            <article v-for="item in worktrees" :key="item.id" class="git-item">
              <div>
                <strong>{{ item.branch }}</strong
                ><span>task {{ item.task_key }}</span>
                <small
                  >HEAD {{ shortSha(item.head_sha) }} · pushed
                  {{ shortSha(item.last_pushed_sha) }}</small
                >
              </div>
              <div class="item-actions">
                <a-tag :color="statusColor(item.status)">{{ item.status }}</a-tag>
                <a-popconfirm v-if="item.usage_mode === 'worktree'" title="确认回收工作树目录（含忽略文件）？远端分支保留；未提交或未推送时将拒绝清理。" @confirm="cleanupWorktree(item)">
                  <a-button size="small" :disabled="!['ready', 'cleanup_failed'].includes(item.status)">安全清理</a-button>
                </a-popconfirm>
              </div>
              <GitWorktreeArtifactPanel v-if="item.usage_mode === 'worktree' && item.status === 'ready'" :project-id="project.id" :worktree="item" @updated="load({ quiet: true })" />
            </article>
          </div>
        </a-spin>
      </component>
      <component :is="section === 'all' ? 'a-tab-pane' : 'section'" v-if="section === 'all' || section === 'occupancies'" key="occupancies" tab="占用与排队">
        <ProjectGitActivityPanel v-if="activeTab === 'occupancies'" :project-id="project.id" kind="occupancies" :resources="repositories" />
      </component>
      <component :is="section === 'all' ? 'a-tab-pane' : 'section'" v-if="section === 'all' || section === 'history'" key="history" tab="审批与历史">
        <ProjectGitActivityPanel v-if="activeTab === 'history'" :project-id="project.id" kind="history" :resources="repositories" />
      </component>
    </component>
  </component>
</template>

<script setup>
import { useProjectThemeEdit } from '@/composables/useProjectThemeEdit'
import { computed, inject, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { QuestionCircleOutlined } from '@ant-design/icons-vue'
import { gitApi } from '@/apis/git_api'
import { projectApi } from '@/apis/project_api'
import ProjectGitActivityPanel from '@/components/ProjectGitActivityPanel.vue'
import GitWorktreeArtifactPanel from '@/components/GitWorktreeArtifactPanel.vue'
import GitResourcePanel from '@/components/GitResourcePanel.vue'

const props = defineProps({ embedded: Boolean, open: Boolean, project: { type: Object, default: null }, section: { type: String, default: 'all' }, autoRefresh: { type: Boolean, default: true } })
const emit = defineEmits(['update:open', 'updated'])
const { openSettingsModal } = inject('settingsModal', {})
const activeTab = ref('repositories')
const loading = ref(false)
const savingRepository = ref(false)
const savingPolicyId = ref('')
const error = ref('')
const showRepositoryForm = ref(false)
const connections = ref([])
const repositories = ref([])
const worktrees = ref([])
const policyDrafts = reactive({})
const policySnapshots = reactive({})
let pollTimer = null

// 服务器当前值的快照；草稿未修改时跟随快照，修改后保留用户输入
const snapshotPolicy = (item) => ({
  purpose: item.purpose || '项目仓库',
  // configured_base_branch 留空表示跟随远端默认分支，不能用 default_branch 回填，
  // 否则保存时会把"跟随远端"隐式固化为 pinned 值
  configured_base_branch: item.configured_base_branch || '',
  allowed_base_branches: [...(item.allowed_base_branches || [])]
})
const clonePolicy = (policy) => ({
  ...policy,
  allowed_base_branches: [...policy.allowed_base_branches]
})
const isPolicyDirty = (id) => {
  const draft = policyDrafts[id]
  const snap = policySnapshots[id]
  if (!draft || !snap) return false
  return (
    draft.purpose !== snap.purpose ||
    draft.configured_base_branch !== snap.configured_base_branch ||
    JSON.stringify(draft.allowed_base_branches) !== JSON.stringify(snap.allowed_base_branches)
  )
}

const repositoryForm = reactive({
  connection_id: '',
  alias: '',
  repository_owner: '',
  repository_name: '',
  purpose: '项目仓库',
  configured_base_branch: '',
  allowed_base_branches: [],
  checkout_path: '',
  usage_mode: 'worktree',
  approval_mode: 'protected'
})
useProjectThemeEdit('项目仓库配置', () => props.project?.id, () => Boolean((props.embedded || props.open) && (Object.keys(policyDrafts).some(isPolicyDirty) || selectedRepositoryId.value || repositoryForm.alias || repositoryForm.checkout_path)), () => {for(const id of Object.keys(policyDrafts))policyDrafts[id]=clonePolicy(policySnapshots[id]);resetRepositorySelection()}, () => savingRepository.value || Boolean(savingPolicyId.value), true)
const discoveryError = ref('')
const remoteRepositories = ref([])
const remoteBranches = ref([])
const selectedRepositoryId = ref('')
const loadingRemoteRepositories = ref(false)
const loadingRemoteBranches = ref(false)
let discoveryGeneration = 0

const resetRepositorySelection = () => {
  selectedRepositoryId.value = ''
  remoteBranches.value = []
  Object.assign(repositoryForm, { alias: '', repository_owner: '', repository_name: '', configured_base_branch: '', allowed_base_branches: [], checkout_path: '' })
}
const loadRemoteRepositories = async () => {
  const version = ++discoveryGeneration
  discoveryError.value = ''
  const connectionId = repositoryForm.connection_id
  resetRepositorySelection()
  remoteRepositories.value = []
  loadingRemoteBranches.value = false
  if (!connectionId) return
  loadingRemoteRepositories.value = true
  try {
    const result = await gitApi.getConnectionRepositories(connectionId)
    if (version === discoveryGeneration) remoteRepositories.value = result
  } catch (failure) {
    if (version === discoveryGeneration) discoveryError.value = failure?.message || '仓库列表读取失败'
  } finally {
    if (version === discoveryGeneration) loadingRemoteRepositories.value = false
  }
}
const selectRemoteRepository = async (id) => {
  const version = ++discoveryGeneration
  discoveryError.value = ''
  const repository = remoteRepositories.value.find((item) => item.id === id)
  if (!repository) return
  remoteBranches.value = []
  Object.assign(repositoryForm, {
    repository_owner: repository.owner, repository_name: repository.name, alias: repository.name,
    checkout_path: repository.name, configured_base_branch: repository.default_branch,
    allowed_base_branches: []
  })
  loadingRemoteBranches.value = true
  try {
    const result = await gitApi.getConnectionBranches(repositoryForm.connection_id, repository.owner, repository.name)
    if (version === discoveryGeneration) remoteBranches.value = result
  } catch (failure) {
    if (version === discoveryGeneration) discoveryError.value = failure?.message || '分支列表读取失败'
  } finally {
    if (version === discoveryGeneration) loadingRemoteBranches.value = false
  }
}
watch(() => repositoryForm.connection_id, loadRemoteRepositories)
watch([() => props.open, () => props.project?.id], () => {
  discoveryGeneration++
  discoveryError.value = ''
  resetRepositorySelection()
  remoteRepositories.value = []
  loadingRemoteRepositories.value = false
  loadingRemoteBranches.value = false
  repositoryForm.connection_id = ''
})

const canBindRepository = computed(() => !!selectedRepositoryId.value && !loadingRemoteRepositories.value && !loadingRemoteBranches.value && remoteBranches.value.some((branch) => branch.name === repositoryForm.configured_base_branch))
const activeConnections = computed(() =>
  connections.value.filter((item) => item.status === 'active')
)

const load = async ({ quiet = false } = {}) => {
  if (!props.project?.id) return
  if (!quiet) loading.value = true
  try {
    const [connectionRows, repositoryRows, worktreeRows] = await Promise.all([
      gitApi.getConnections(),
      projectApi.getRepositories(props.project.id),
      props.section === 'repositories' ? Promise.resolve([]) : projectApi.getGitWorktrees(props.project.id)
    ])
    connections.value = connectionRows
    if (!repositoryForm.connection_id && activeConnections.value.length === 1) repositoryForm.connection_id = activeConnections.value[0].id
    repositories.value = repositoryRows
    repositoryRows.forEach((item) => {
      policySnapshots[item.id] = snapshotPolicy(item)
      // 用户已修改的草稿不被轮询覆盖；未修改的跟随服务器最新值
      if (!policyDrafts[item.id] || !isPolicyDirty(item.id)) {
        policyDrafts[item.id] = clonePolicy(policySnapshots[item.id])
      }
    })
    worktrees.value = worktreeRows
    emit('updated')
    error.value = ''
  } catch (requestError) {
    error.value = requestError?.message || 'Git 配置加载失败'
  } finally {
    loading.value = false
  }
}

const createRepository = async () => {
  if (!canBindRepository.value) return
  savingRepository.value = true
  try {
    await projectApi.createRepository(props.project.id, {
      request_id: crypto.randomUUID(),
      ...repositoryForm,
      checkout_path: repositoryForm.checkout_path || null
    })
    resetRepositorySelection()
    repositoryForm.purpose = '项目仓库'
    repositoryForm.configured_base_branch = ''
    repositoryForm.allowed_base_branches = []
    await load({ quiet: true })
    showRepositoryForm.value = false
  } catch (requestError) {
    error.value = requestError?.message || '仓库绑定失败'
  } finally {
    savingRepository.value = false
  }
}

const savePolicy = async (item) => {
  const draft = policyDrafts[item.id]
  if (!draft) return
  savingPolicyId.value = item.id
  try {
    await projectApi.updateRepositoryPolicy(props.project.id, item.id, {
      purpose: draft.purpose,
      configured_base_branch: draft.configured_base_branch || null,
      allowed_base_branches: draft.allowed_base_branches || []
    })
    await load({ quiet: true })
    message.success('仓库策略已更新，仅影响未来任务')
  } catch (requestError) {
    error.value = requestError?.message || '仓库策略更新失败'
  } finally {
    savingPolicyId.value = ''
  }
}

const restorePolicy = (item) => {
  if (!policySnapshots[item.id]) return
  policyDrafts[item.id] = clonePolicy(policySnapshots[item.id])
}

const retryRepository = async (item) => {
  try {
    await projectApi.retryRepository(props.project.id, item.id)
    await load({ quiet: true })
  } catch (requestError) {
    error.value = requestError?.message || '重试失败'
  }
}

const deactivateRepository = async (item) => {
  try {
    await projectApi.deactivateRepository(props.project.id, item.id)
    await load({ quiet: true })
  } catch (requestError) {
    error.value = requestError?.message || '停用失败'
  }
}

const cleanupWorktree = async (item) => {
  try {
    await projectApi.cleanupGitWorktree(props.project.id, item.id)
    await load({ quiet: true })
    message.success('Worktree 清理任务已提交，远端分支将保留')
  } catch (requestError) {
    error.value = requestError?.message || 'Worktree 当前不能安全清理'
  }
}

const statusColor = (status) => {
  if (['active', 'ready'].includes(status)) return 'green'
  if (status?.includes('failed')) return 'red'
  if (['provisioning', 'deleting', 'preparing', 'cleanup_pending'].includes(status)) return 'blue'
  return 'default'
}
const shortSha = (sha) => (sha ? sha.slice(0, 10) : '—')

watch(
  () => [props.open, props.project?.id],
  ([open]) => {
    clearInterval(pollTimer)
    if (!open) return
    load()
    if (props.autoRefresh) pollTimer = setInterval(() => load({ quiet: true }), 3000)
  },
  { immediate: true }
)
onBeforeUnmount(() => clearInterval(pollTimer))
defineExpose({ refresh: load })
</script>

<style scoped lang="less">
.connection-hint { font-size:12px; line-height:1.6; color:var(--color-text-secondary); margin:8px 0 0; }
.git-alert {
  margin-bottom: 12px;
}
.section-head {
  display: flex;
  justify-content: flex-start;
  margin-bottom: 10px;
}
.create-form {
  padding: 14px;
  margin-bottom: 18px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 14px;
}
.full-row {
  grid-column: 1 / -1;
}
.item-list {
  display: grid;
  gap: 8px;
}
.git-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px 16px;
  align-items: center;
  padding: 12px 14px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--gray-0);
}
.git-item div:first-child {
  display: grid;
  min-width: 0;
  gap: 2px;
}
.git-item span,
.git-item small {
  overflow: hidden;
  color: var(--gray-500);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.item-error {
  grid-column: 1 / -1;
  margin: 0;
  color: var(--color-error-700);
  font-size: 12px;
}
.policy-editor {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
  gap: 12px;
  margin-top: 4px;
  padding: 12px 14px;
  border: 1px solid var(--gray-150);
  border-radius: 8px;
  background: var(--gray-25);
}
.policy-field {
  display: grid;
  min-width: 0;
  gap: 4px;
}
.policy-field-wide {
  grid-column: 1 / -1;
}
.policy-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--gray-600);
  font-size: 12px;
}
.policy-help {
  color: var(--gray-400);
  font-size: 12px;
  cursor: help;
}
.policy-actions {
  grid-column: 1 / -1;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
@media (max-width: 640px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
  .git-item {
    grid-template-columns: 1fr;
  }
  .item-actions {
    justify-content: flex-start;
  }
  .policy-editor {
    grid-template-columns: 1fr;
  }
}
</style>
