import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = (relativePath) =>
  readFile(new URL(`../../${relativePath}`, import.meta.url), 'utf8')

test('任务仓库 API 只接受 thread identity 与仓库意图', async () => {
  const source = await readSource('src/apis/agent_api.js')

  assert.match(source, /getGitRepositories: \(threadId\).*git-repositories/s)
  assert.match(source, /selectGitRepository: \(threadId, payload\).*apiPost/s)
  assert.match(source, /retryGitRepository: \(threadId, repositoryId\).*\/retry/s)
})

test('任务仓库弹窗按仓库独立保存并展示部分成功', async () => {
  const source = await readSource('src/components/ConversationGitRepositoriesModal.vue')

  assert.match(source, /for \(const item of selected\)/)
  assert.match(source, /failures\.push/)
  assert.match(source, /部分仓库未保存/)
  assert.match(source, /crypto\.randomUUID\(\)/)
  assert.match(source, /v-if="item\.allocation"/)
  assert.match(source, /v-else>[\s\S]*为当前任务选择/)
})

test('不可编辑 allocation 提供显式重试与清理且轮询最终状态', async () => {
  const source = await readSource('src/components/ConversationGitRepositoriesModal.vue')

  assert.match(source, /status === 'prepare_failed'/)
  assert.match(source, /retryGitRepository/)
  assert.match(source, /cleanupGitWorktree/)
  assert.match(source, /setInterval\(\(\) => load\(\{ quiet: true \}\), 3000\)/)
  assert.match(source, /@media \(max-width: 640px\)/)
})

test('Project Git 设置暴露用途与基线策略更新', async () => {
  const source = await readSource('src/components/ProjectGitSettingsModal.vue')
  const api = await readSource('src/apis/project_api.js')

  assert.match(source, /purpose/)
  assert.match(source, /configured_base_branch/)
  assert.match(source, /allowed_base_branches/)
  assert.match(source, /updateRepositoryPolicy/)
  assert.match(api, /repositories\/\$\{repositoryId\}\/policy/)
})
