<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { useUserStore } from '@/stores/user'
import { loadProjectGitAttention } from '@/utils/projectGitAttention'
const props = defineProps({ projectId: { type: String, required: true }, section: { type: String, default: 'all' } })
const user = useUserStore(), pending = ref([]), occupancies = ref([]), error = ref('')
let generation = 0, timer
/** 总览只投影当前待办；空列表不占据页面。 */
async function refresh() {
  clearTimeout(timer)
  const version = generation
  try {
    const result = await loadProjectGitAttention(props.projectId, props.section)
    if (version !== generation) return
    pending.value = result.pending; occupancies.value = result.occupancies; error.value = ''
  } catch (cause) {
    if (version !== generation) return
    error.value = cause.message || 'Git 待办读取失败'
    if ([401,403,404].includes(cause.status || cause.response?.status)) { pending.value = []; occupancies.value = [] }
  } finally {
    if (version === generation) timer = setTimeout(refresh, 10000)
  }
}
const target = (section, action) => ({ name: 'ProjectSettings', params: { project_id: props.projectId }, query: { git_section: section, ...(action ? { git_action: action } : {}) }, hash: section === 'approvals' ? '#git-approvals' : '#git-occupancies' })
watch(() => [props.projectId, props.section, user.uid], () => { generation++; clearTimeout(timer); pending.value = []; occupancies.value = []; error.value = ''; void refresh() }, { immediate: true })
onBeforeUnmount(() => { generation++; clearTimeout(timer) })
</script>
<template>
  <section v-if="error || pending.length || occupancies.length" class="git-attention">
    <a-alert v-if="error" type="warning" show-icon :message="`资源待办尚未更新：${error}`" />
    <div v-if="pending.length"><RouterLink class="attention-heading" :to="target('approvals')">待人工审批 <span>{{ pending.length }}</span></RouterLink><RouterLink v-for="row in pending.slice(0, 3)" :key="row.id" class="attention-row" :to="target('approvals', row.id)">{{ `${({commit:'提交',push:'推送',merge:'合并'})[row.action] || 'Git 操作'} · ${row.branch || ''} · ${row.approval_reason || '等待人工判断'}` }}</RouterLink></div>
    <div v-if="occupancies.length"><RouterLink class="attention-heading" :to="target('occupancies')">资源占用与排队 <span>{{ occupancies.length }}</span></RouterLink><RouterLink v-for="row in occupancies.slice(0, 3)" :key="row.id" class="attention-row" :to="target('occupancies')"><span>{{ row.scope_label || row.repository_alias || '项目工作空间' }}</span><small>{{ row.status === 'queued' ? '排队中' : '使用中' }}</small></RouterLink></div>
  </section>
</template>
<style scoped>
.git-attention { display:grid; gap:18px; padding:22px; background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; }.git-attention a,.git-attention a:hover,.git-attention a:focus { text-decoration:none; }.attention-heading { display:flex; gap:8px; align-items:center; font-size:15px; font-weight:600; color:var(--color-text); }.attention-heading span { color:var(--main-color); font-size:13px; }.attention-row { display:flex; justify-content:space-between; gap:12px; padding-top:10px; font-size:13px; color:var(--color-text-secondary); overflow-wrap:anywhere; }.attention-row small { white-space:nowrap; }
</style>
