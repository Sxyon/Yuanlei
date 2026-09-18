<template>
  <a-modal
    :open="open"
    title="任务仓库"
    width="880px"
    :footer="null"
    @cancel="emit('update:open', false)"
  >
    <a-alert
      v-if="error"
      class="task-git-alert"
      type="error"
      show-icon
      closable
      :message="error"
      @close="error = ''"
    />
    <p class="task-git-help">
      Project 仓库不会自动分配。保存后，下次运行只准备这里选择的仓库。
    </p>
    <a-spin :spinning="loading">
      <a-empty v-if="!repositories.length" description="当前 Project 尚未配置 Git 仓库" />
      <div v-else class="task-repository-list">
        <article v-for="item in repositories" :key="item.id" class="task-repository-card">
          <header>
            <div>
              <strong>{{ item.alias }}</strong>
              <span>{{ item.purpose }}</span>
            </div>
            <a-tag :color="statusColor(item.allocation?.status || item.status)">
              {{ item.allocation?.status || item.status }}
            </a-tag>
          </header>

          <template v-if="item.allocation">
            <dl class="allocation-summary">
              <div><dt>任务用途</dt><dd>{{ item.allocation.task_purpose }}</dd></div>
              <div><dt>分支</dt><dd>{{ item.allocation.branch }}</dd></div>
              <div><dt>基线</dt><dd>{{ item.allocation.base_branch }}</dd></div>
              <div v-if="item.allocation.sandbox_path">
                <dt>Sandbox</dt><dd>{{ item.allocation.sandbox_path }}</dd>
              </div>
            </dl>
            <p v-if="item.allocation.last_error_message" class="item-error">
              {{ item.allocation.last_error_message }}
            </p>
            <div class="card-actions">
              <a-button
                v-if="item.allocation.status === 'prepare_failed'"
                size="small"
                :loading="busyRepositoryId === item.id"
                @click="retry(item)"
              >重试准备</a-button>
              <a-popconfirm
                v-if="['requested', 'ready', 'prepare_failed', 'cleanup_failed'].includes(item.allocation.status)"
                title="清理后才能为该仓库选择新的分支意图，是否继续？"
                @confirm="cleanup(item)"
              >
                <a-button size="small" danger :loading="busyRepositoryId === item.id">显式清理</a-button>
              </a-popconfirm>
            </div>
          </template>

          <template v-else>
            <a-checkbox
              v-model:checked="drafts[item.id].selected"
              :disabled="item.status !== 'active'"
            >为当前任务选择</a-checkbox>
            <div v-if="drafts[item.id].selected" class="allocation-form">
              <a-form-item label="Base branch" required>
                <a-select v-model:value="drafts[item.id].base_branch">
                  <a-select-option
                    v-for="branch in item.allowed_base_branches"
                    :key="branch"
                    :value="branch"
                  >{{ branch }}</a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item label="分支类型" required>
                <a-select v-model:value="drafts[item.id].branch_kind">
                  <a-select-option v-for="kind in branchKinds" :key="kind" :value="kind">
                    {{ kind }}
                  </a-select-option>
                </a-select>
              </a-form-item>
              <a-form-item label="分支描述" required>
                <a-input
                  v-model:value="drafts[item.id].branch_slug"
                  maxlength="48"
                  placeholder="例如 order-refund"
                />
              </a-form-item>
              <a-form-item label="任务用途" required>
                <a-input
                  v-model:value="drafts[item.id].task_purpose"
                  maxlength="500"
                  placeholder="为什么需要该仓库"
                />
              </a-form-item>
            </div>
          </template>
        </article>
      </div>
    </a-spin>
    <div class="modal-actions">
      <a-button @click="emit('update:open', false)">关闭</a-button>
      <a-button type="primary" :loading="saving" :disabled="!hasPendingSelection" @click="save">
        保存选择
      </a-button>
    </div>
  </a-modal>
</template>

<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { message } from 'ant-design-vue'
import { threadApi } from '@/apis'
import { projectApi } from '@/apis/project_api'

const props = defineProps({
  open: Boolean,
  threadId: { type: String, default: '' },
  projectId: { type: String, default: '' }
})
const emit = defineEmits(['update:open'])
const branchKinds = ['feature', 'fix', 'docs', 'refactor', 'chore', 'test']
const repositories = ref([])
const drafts = reactive({})
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const busyRepositoryId = ref('')
let pollTimer = null

const hasPendingSelection = computed(() =>
  repositories.value.some((item) => !item.allocation && drafts[item.id]?.selected)
)

const syncDrafts = (rows) => {
  rows.forEach((item) => {
    if (item.allocation || drafts[item.id]) return
    drafts[item.id] = {
      selected: false,
      base_branch: item.default_base_branch || item.allowed_base_branches?.[0] || '',
      branch_kind: 'feature',
      branch_slug: '',
      task_purpose: ''
    }
  })
}

const load = async ({ quiet = false } = {}) => {
  if (!props.threadId) return
  if (!quiet) loading.value = true
  try {
    const rows = await threadApi.getGitRepositories(props.threadId)
    repositories.value = rows
    syncDrafts(rows)
    error.value = ''
  } catch (requestError) {
    error.value = requestError?.message || '任务仓库加载失败'
  } finally {
    loading.value = false
  }
}

const save = async () => {
  const selected = repositories.value.filter(
    (item) => !item.allocation && drafts[item.id]?.selected
  )
  saving.value = true
  const failures = []
  for (const item of selected) {
    const draft = drafts[item.id]
    try {
      await threadApi.selectGitRepository(props.threadId, {
        request_id: crypto.randomUUID(),
        repository_alias: item.alias,
        base_branch: draft.base_branch,
        branch_kind: draft.branch_kind,
        branch_slug: draft.branch_slug,
        task_purpose: draft.task_purpose
      })
      draft.selected = false
    } catch (requestError) {
      failures.push(`${item.alias}: ${requestError?.message || '保存失败'}`)
    }
  }
  await load({ quiet: true })
  saving.value = false
  if (failures.length) {
    error.value = `部分仓库未保存：${failures.join('；')}`
  } else {
    message.success('任务仓库选择已保存，将在下次运行前准备')
  }
}

const retry = async (item) => {
  busyRepositoryId.value = item.id
  try {
    await threadApi.retryGitRepository(props.threadId, item.id)
    await load({ quiet: true })
  } catch (requestError) {
    error.value = requestError?.message || '任务仓库重试失败'
  } finally {
    busyRepositoryId.value = ''
  }
}

const cleanup = async (item) => {
  if (!props.projectId) return
  busyRepositoryId.value = item.id
  try {
    await projectApi.cleanupGitWorktree(props.projectId, item.allocation.id)
    await load({ quiet: true })
  } catch (requestError) {
    error.value = requestError?.message || '任务仓库当前不能安全清理'
  } finally {
    busyRepositoryId.value = ''
  }
}

const statusColor = (status) => {
  if (['active', 'ready'].includes(status)) return 'green'
  if (status?.includes('failed')) return 'red'
  if (['requested', 'preparing', 'provisioning', 'cleanup_pending'].includes(status)) return 'blue'
  return 'default'
}

watch(
  () => [props.open, props.threadId],
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
.task-git-alert {
  margin-bottom: 12px;
}
.task-git-help {
  color: var(--gray-500);
}
.task-repository-list {
  display: grid;
  gap: 10px;
}
.task-repository-card {
  padding: 14px;
  border: 1px solid var(--gray-200);
  border-radius: 10px;
  background: var(--gray-0);
}
.task-repository-card header,
.task-repository-card header > div {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}
.task-repository-card header span,
.task-repository-card dd {
  color: var(--gray-500);
}
.allocation-form {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 12px;
  margin-top: 12px;
}
.allocation-summary {
  display: grid;
  gap: 6px;
}
.allocation-summary div {
  display: grid;
  grid-template-columns: 80px minmax(0, 1fr);
}
.allocation-summary dt,
.allocation-summary dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.item-error {
  color: var(--color-error-700);
}
.card-actions,
.modal-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}
.modal-actions {
  margin-top: 18px;
}
@media (max-width: 640px) {
  .allocation-form {
    grid-template-columns: 1fr;
  }
  .task-repository-card header,
  .task-repository-card header > div {
    align-items: flex-start;
  }
}
</style>
