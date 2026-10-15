<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { projectApi } from '@/apis/project_api'
import { loadProjectGitAttention } from '@/utils/projectGitAttention'
import GitResourcePanel from './GitResourcePanel.vue'
import GitWorktreeArtifactPanel from './GitWorktreeArtifactPanel.vue'
import ProjectGitActivityPanel from './ProjectGitActivityPanel.vue'
const props = defineProps({ projectId: { type: String, required: true } })
const route = useRoute(), user = useUserStore()
const resources = ref([]), worktrees = ref([]), occupancies = ref([]), pending = ref([])
const loading = ref(false), paused = ref(false), error = ref(''), historyOpen = ref(false), refreshToken = ref(0), updatedAt = ref(''), pendingPanel = ref(null)
let generation = 0, timer, handledSection = '', handledAction = ''
/** 只刷新投影；人工提交弹窗由资源组件保留冻结快照。 */
async function refresh() {
  if (loading.value) return
  const version = generation, owner = user.uid, project = props.projectId
  loading.value = true
  clearTimeout(timer)
  try {
    const [repos, trees, attention] = await Promise.all([projectApi.getRepositories(project), projectApi.getGitWorktrees(project), loadProjectGitAttention(project)])
    if (version !== generation || owner !== user.uid) return
    resources.value = repos; worktrees.value = trees; occupancies.value = attention.occupancies; pending.value = attention.pending
    error.value = ''; updatedAt.value = new Date().toLocaleTimeString(); refreshToken.value++
  } catch (cause) {
    if (version === generation) {
      error.value = cause.message || '资源状态刷新失败'
      if ([401,403,404].includes(cause.status || cause.response?.status)) { resources.value = []; worktrees.value = []; occupancies.value = []; pending.value = []; historyOpen.value = false; paused.value = true }
    }
  } finally {
    if (version === generation) { loading.value = false; if (!paused.value) timer = setTimeout(refresh, 5000) }
  }
}
watch(paused, value => { clearTimeout(timer); if (!value) void refresh() })
watch(() => [props.projectId, user.uid], () => {
  generation++; clearTimeout(timer); loading.value = false; handledSection = ''; handledAction = ''
  resources.value = []; worktrees.value = []; occupancies.value = []; pending.value = []; error.value = ''; updatedAt.value = ''; historyOpen.value = false
  void refresh()
}, { immediate: true })
watch(() => [route.query.git_section, route.query.git_action, pending.value], async () => {
  await nextTick()
  const id = route.query.git_section === 'occupancies' ? 'git-occupancies' : route.query.git_section === 'approvals' ? 'git-approvals' : ''
  if (id && handledSection !== id) { const target = document.getElementById(id); if (target) { target.open = true; target.scrollIntoView({ block: 'start' }) } handledSection = id }
  if (!id) handledSection = ''
  const action = String(route.query.git_action || '')
  if (!action) handledAction = ''
  if (action && action !== handledAction && pending.value.some(row => row.id === action)) { pendingPanel.value?.openAction(action); handledAction = action }
}, { immediate: true })
onBeforeUnmount(() => { generation++; clearTimeout(timer) })
defineExpose({ refresh })
</script>
<template>
  <div class="git-workspace">
    <div class="monitor-tools"><span role="status">{{ error ? '刷新失败' : paused ? '已暂停自动刷新' : '每5秒刷新' }}<small v-if="updatedAt"> · {{ updatedAt }}</small></span><div><a-button size="small" :loading="loading" @click="refresh">刷新</a-button><a-button size="small" :aria-pressed="paused" @click="paused = !paused">{{ paused ? '恢复刷新' : '暂停刷新' }}</a-button><a-button size="small" @click="historyOpen = true">历史记录</a-button></div></div>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <details open id="git-approvals" class="git-workspace-card"><summary><h3>待人工审批 <small>{{ pending.length }}</small></h3></summary><p v-if="route.query.git_action && !loading && !pending.some(row => row.id === route.query.git_action)" class="muted">该申请已不在待审批列表，可在历史记录中核对。</p><div class="fixed-activity-list" :class="{ empty: !pending.length }"><ProjectGitActivityPanel ref="pendingPanel" :project-id="projectId" kind="pending" :items="pending" :resources="resources" :auto-refresh="false" @refresh="refresh" /></div></details>
    <details open class="git-workspace-card"><summary><h3>改动与提交</h3></summary><div class="fixed-resource-list"><article v-for="resource in resources.filter(item => ['active','provision_failed'].includes(item.status))" :key="resource.id" class="live-repository"><GitResourcePanel :project-id="projectId" :resource="resource" mode="activity" :refresh-token="refreshToken" @updated="refresh" /></article><a-empty v-if="!resources.some(item => ['active','provision_failed'].includes(item.status)) && !loading" description="尚未绑定仓库，可在右侧仓库卡片配置" /></div></details>
    <details open id="git-occupancies" class="git-workspace-card"><summary><h3>占用与排队 <small>{{ occupancies.length }}</small></h3></summary><div class="fixed-activity-list" :class="{ empty: !occupancies.length }"><ProjectGitActivityPanel :project-id="projectId" kind="occupancies" :items="occupancies" :resources="resources" :auto-refresh="false" @refresh="refresh" /></div></details>
    <details open class="git-workspace-card"><summary><h3>Worktrees</h3></summary><div class="fixed-worktree-list"><article v-for="tree in worktrees" :key="tree.id" class="worktree-row"><strong>{{ tree.branch }}</strong><small>{{ tree.status }} · {{ tree.task_key }}</small><details v-if="tree.usage_mode === 'worktree' && ['ready','cleanup_failed'].includes(tree.status)"><summary>成果与安全清理</summary><GitWorktreeArtifactPanel v-if="tree.status === 'ready'" :project-id="projectId" :worktree="tree" @updated="refresh" /><a-popconfirm title="回收工作树目录？未提交或未推送时拒绝清理，远端分支保留。" @confirm="projectApi.cleanupGitWorktree(projectId, tree.id).then(refresh).catch(cause => error = cause.message)"><a-button size="small" danger>安全清理</a-button></a-popconfirm></details></article><a-empty v-if="!worktrees.length" description="暂无工作树" /></div></details>
    <a-modal v-model:open="historyOpen" title="Git 历史与追溯" :width="1000" :footer="null" :destroy-on-close="true"><ProjectGitActivityPanel v-if="historyOpen" :project-id="projectId" kind="history" :resources="resources" :auto-refresh="false" /></a-modal>
  </div>
</template>
<style scoped lang="less">
.git-workspace { display:grid; gap:20px; }.monitor-tools { display:flex; align-items:center; justify-content:space-between; gap:12px; flex-wrap:wrap; font-size:12px; color:var(--color-text-secondary); >div { display:flex; gap:6px; flex-wrap:wrap; } }
.git-workspace-card { min-width:0; padding:22px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; scroll-margin-top:20px; h3 { font-size:16px; margin:0 0 16px; } h3 small { color:var(--color-text-secondary); font-size:12px; font-weight:400; margin-left:8px; } }
.git-workspace-card summary { display:flex; align-items:center; justify-content:space-between; cursor:pointer; list-style:none; } .git-workspace-card summary::-webkit-details-marker { display:none; } .git-workspace-card summary::after { content:"⌄"; color:var(--color-text-secondary); transform:rotate(-90deg); } .git-workspace-card[open] summary::after { transform:none; } .git-workspace-card summary h3 { margin:0; } .git-workspace-card[open] summary { margin-bottom:16px; }
.fixed-resource-list { height:480px; overflow:auto; scrollbar-gutter:stable; }.fixed-activity-list { height:260px; overflow:auto; scrollbar-gutter:stable; }.fixed-activity-list.empty { height:120px; :deep(.ant-empty) { margin:12px 0; } :deep(.ant-empty-image) { height:48px; } }.fixed-worktree-list { max-height:240px; min-height:100px; overflow:auto; scrollbar-gutter:stable; }
.live-repository+.live-repository,.worktree-row+.worktree-row { border-top:1px solid var(--gray-150); margin-top:16px; padding-top:16px; }.worktree-row { display:grid; gap:6px; font-size:13px; small,.muted { color:var(--color-text-secondary); } details>summary { cursor:pointer; } }
@media(max-width:760px){.git-workspace-card { padding:18px; }}
</style>
