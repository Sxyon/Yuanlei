<template>
  <a-modal
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
    <a-tabs v-model:active-key="activeTab">
      <a-tab-pane key="repositories" tab="仓库">
        <a-form layout="vertical" class="create-form">
          <div class="form-grid">
            <a-form-item label="Connection" required>
              <a-select
                v-model:value="repositoryForm.connection_id"
                placeholder="选择 Gitea connection"
              >
                <a-select-option v-for="item in activeConnections" :key="item.id" :value="item.id">
                  {{ item.name }}
                </a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item label="Alias" required>
              <a-input v-model:value="repositoryForm.alias" maxlength="80" placeholder="例如 api" />
            </a-form-item>
            <a-form-item label="Owner" required>
              <a-input v-model:value="repositoryForm.repository_owner" placeholder="Gitea owner" />
            </a-form-item>
            <a-form-item label="Repository" required>
              <a-input v-model:value="repositoryForm.repository_name" placeholder="仓库名" />
            </a-form-item>
            <a-form-item label="仓库用途" required>
              <a-input v-model:value="repositoryForm.purpose" maxlength="500" placeholder="例如 后端 API" />
            </a-form-item>
            <a-form-item label="默认任务基线">
              <a-input
                v-model:value="repositoryForm.configured_base_branch"
                maxlength="255"
                placeholder="留空时使用远端默认分支"
              />
            </a-form-item>
            <a-form-item class="full-row" label="允许的任务基线">
              <a-select
                v-model:value="repositoryForm.allowed_base_branches"
                mode="tags"
                :max-tag-count="4"
                placeholder="留空时使用默认任务基线"
              />
            </a-form-item>
          </div>
          <a-button
            type="primary"
            html-type="button"
            :loading="savingRepository"
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
                  {{ item.configured_base_branch || item.default_branch || '等待读取' }}
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
              <p v-if="item.last_error_message" class="item-error">{{ item.last_error_message }}</p>
              <div v-if="item.status === 'active' && policyDrafts[item.id]" class="policy-editor">
                <a-input
                  v-model:value="policyDrafts[item.id].purpose"
                  maxlength="500"
                  aria-label="仓库用途"
                />
                <a-input
                  v-model:value="policyDrafts[item.id].configured_base_branch"
                  maxlength="255"
                  aria-label="默认任务基线"
                />
                <a-select
                  v-model:value="policyDrafts[item.id].allowed_base_branches"
                  mode="tags"
                  :max-tag-count="3"
                  aria-label="允许的任务基线"
                />
                <a-button
                  size="small"
                  :loading="savingPolicyId === item.id"
                  @click="savePolicy(item)"
                >保存策略</a-button>
              </div>
            </article>
          </div>
        </a-spin>
      </a-tab-pane>

      <a-tab-pane key="connections" tab="Connections">
        <a-form layout="vertical" class="create-form">
          <div class="form-grid">
            <a-form-item label="名称" required
              ><a-input v-model:value="connectionForm.name"
            /></a-form-item>
            <a-form-item label="API Origin" required>
              <a-input
                v-model:value="connectionForm.api_origin"
                placeholder="https://gitea.example.com"
              />
            </a-form-item>
            <a-form-item label="SSH Host" required
              ><a-input v-model:value="connectionForm.ssh_host"
            /></a-form-item>
            <a-form-item label="SSH Port" required>
              <a-input-number v-model:value="connectionForm.ssh_port" :min="1" :max="65535" />
            </a-form-item>
          </div>
          <a-form-item label="SSH known-host key" required>
            <a-textarea v-model:value="connectionForm.ssh_known_host_key" :rows="2" />
          </a-form-item>
          <a-form-item label="Gitea API Token（仅本次提交可见）" required>
            <a-input-password
              v-model:value="connectionForm.api_token"
              autocomplete="new-password"
            />
          </a-form-item>
          <a-button
            type="primary"
            html-type="button"
            :loading="savingConnection"
            @click="createConnection"
            >创建 connection</a-button
          >
        </a-form>
        <a-empty v-if="!connections.length" description="尚未创建 connection" />
        <div v-else class="item-list">
          <article v-for="item in connections" :key="item.id" class="git-item">
            <div>
              <strong>{{ item.name }}</strong
              ><span>{{ item.api_origin }}</span>
              <small>{{ item.ssh_host }}:{{ item.ssh_port }}</small>
            </div>
              <div class="item-actions">
                <a-tag>{{ item.provider }}</a-tag>
                <a-button size="small" @click="beginCredentialUpdate(item)">更新 Token</a-button>
                <a-popconfirm
                title="仅未被仓库使用的 connection 可以删除"
                @confirm="deleteConnection(item)"
              >
                <a-button size="small" danger>删除</a-button>
                </a-popconfirm>
              </div>
              <div v-if="editingConnectionId === item.id" class="credential-update">
                <a-input-password
                  v-model:value="credentialToken"
                  autocomplete="new-password"
                  placeholder="输入新的 Gitea API Token"
                />
                <a-button
                  type="primary"
                  size="small"
                  :loading="updatingCredential"
                  :disabled="!credentialToken"
                  @click="updateConnectionCredential(item)"
                  >保存</a-button
                >
                <a-button size="small" @click="cancelCredentialUpdate">取消</a-button>
              </div>
            </article>
        </div>
      </a-tab-pane>

      <a-tab-pane key="worktrees" tab="Worktrees">
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
                <a-button
                  size="small"
                  :disabled="!['ready', 'cleanup_failed'].includes(item.status)"
                  @click="cleanupWorktree(item)"
                >
                  安全清理
                </a-button>
              </div>
            </article>
          </div>
        </a-spin>
      </a-tab-pane>
    </a-tabs>
  </a-modal>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { gitApi } from '@/apis/git_api'
import { projectApi } from '@/apis/project_api'

const props = defineProps({ open: Boolean, project: { type: Object, default: null } })
const emit = defineEmits(['update:open'])
const activeTab = ref('repositories')
const loading = ref(false)
const savingConnection = ref(false)
const savingRepository = ref(false)
const savingPolicyId = ref('')
const updatingCredential = ref(false)
const editingConnectionId = ref('')
const credentialToken = ref('')
const error = ref('')
const connections = ref([])
const repositories = ref([])
const worktrees = ref([])
const policyDrafts = reactive({})
let pollTimer = null

const connectionForm = reactive({
  name: '',
  api_origin: '',
  ssh_host: '',
  ssh_port: 22,
  ssh_known_host_key: '',
  api_token: ''
})
const repositoryForm = reactive({
  connection_id: '',
  alias: '',
  repository_owner: '',
  repository_name: '',
  purpose: '项目仓库',
  configured_base_branch: '',
  allowed_base_branches: []
})
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
      projectApi.getGitWorktrees(props.project.id)
    ])
    connections.value = connectionRows
    repositories.value = repositoryRows
    repositoryRows.forEach((item) => {
      policyDrafts[item.id] = {
        purpose: item.purpose || '项目仓库',
        configured_base_branch: item.configured_base_branch || item.default_branch || '',
        allowed_base_branches: [...(item.allowed_base_branches || [])]
      }
    })
    worktrees.value = worktreeRows
    error.value = ''
  } catch (requestError) {
    error.value = requestError?.message || 'Git 配置加载失败'
  } finally {
    loading.value = false
  }
}

const createConnection = async () => {
  savingConnection.value = true
  try {
    await gitApi.createConnection({
      request_id: crypto.randomUUID(),
      provider: 'gitea',
      ...connectionForm
    })
    connectionForm.api_token = ''
    connectionForm.ssh_known_host_key = ''
    connectionForm.name = ''
    await load({ quiet: true })
    message.success('Gitea connection 已创建')
  } catch (requestError) {
    connectionForm.api_token = ''
    error.value = requestError?.message || 'Connection 创建失败'
  } finally {
    savingConnection.value = false
  }
}

const createRepository = async () => {
  savingRepository.value = true
  try {
    await projectApi.createRepository(props.project.id, {
      request_id: crypto.randomUUID(),
      ...repositoryForm
    })
    repositoryForm.alias = ''
    repositoryForm.repository_owner = ''
    repositoryForm.repository_name = ''
    repositoryForm.purpose = '项目仓库'
    repositoryForm.configured_base_branch = ''
    repositoryForm.allowed_base_branches = []
    await load({ quiet: true })
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

const deleteConnection = async (item) => {
  try {
    await gitApi.deleteConnection(item.id)
    await load({ quiet: true })
  } catch (requestError) {
    error.value = requestError?.message || 'Connection 删除失败'
  }
}

const beginCredentialUpdate = (item) => {
  credentialToken.value = ''
  editingConnectionId.value = item.id
}

const cancelCredentialUpdate = () => {
  credentialToken.value = ''
  editingConnectionId.value = ''
}

const updateConnectionCredential = async (item) => {
  updatingCredential.value = true
  try {
    await gitApi.updateCredential(item.id, credentialToken.value)
    credentialToken.value = ''
    editingConnectionId.value = ''
    await load({ quiet: true })
    message.success('Gitea Token 已更新')
  } catch (requestError) {
    credentialToken.value = ''
    error.value = requestError?.message || 'Token 更新失败'
  } finally {
    updatingCredential.value = false
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
    pollTimer = setInterval(() => load({ quiet: true }), 3000)
  },
  { immediate: true }
)
onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped lang="less">
.git-alert {
  margin-bottom: 12px;
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
  grid-template-columns: minmax(140px, 1fr) minmax(140px, 1fr) minmax(180px, 2fr) auto;
  gap: 8px;
  align-items: center;
}
.credential-update {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
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
  .credential-update {
    grid-template-columns: 1fr;
  }
  .policy-editor {
    grid-template-columns: 1fr;
  }
}
</style>
