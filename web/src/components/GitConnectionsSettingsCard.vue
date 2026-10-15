<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { Plus, RefreshCw, GitBranch } from '@lucide/vue'
import { gitApi } from '@/apis/git_api'
import { useUserStore } from '@/stores/user'

const props = defineProps({ active: { type: Boolean, default: true } })
const user = useUserStore()
const connections = ref([]), loading = ref(false), busy = ref(false), error = ref(''), success = ref('')
const creating = ref(false), editingId = ref(''), credentialToken = ref('')
const form = reactive({ name: '', api_origin: '', ssh_host: '', ssh_port: 22, ssh_known_host_key: '', api_token: '' })
const canCreate = computed(() => ['name', 'api_origin', 'ssh_host', 'ssh_known_host_key', 'api_token'].every(key => form[key].trim()) && form.ssh_port >= 1 && form.ssh_port <= 65535)
let generation = 0, loadSequence = 0
const scope = () => ({ generation, uid: user.uid })
const current = value => value.generation === generation && value.uid === user.uid
function clearSecrets() { form.api_token = ''; credentialToken.value = '' }
/** 连接属于登录用户，迟到请求不能恢复另一个账号的数据。 */
async function load() {
  const captured = scope(), request = ++loadSequence
  loading.value = true
  try {
    const rows = await gitApi.getConnections()
    if (current(captured) && request === loadSequence) connections.value = rows
  } catch (cause) {
    if (current(captured) && request === loadSequence) {
      error.value = cause.message || 'Git 连接读取失败'
      if ([401, 403].includes(cause.status || cause.response?.status)) { connections.value = []; clearSecrets(); creating.value = false; editingId.value = '' }
    }
  } finally { if (current(captured) && request === loadSequence) loading.value = false }
}
/** 原用户级API执行写入，界面仅在回读后展示列表。 */
async function mutate(action) {
  if (busy.value) return
  const captured = scope()
  busy.value = true; error.value = ''; success.value = ''
  try {
    await action()
    if (!current(captured)) return
    clearSecrets(); creating.value = false; editingId.value = ''
    await load()
    if (current(captured) && !error.value) success.value = '操作已完成，连接列表已更新。'
  } catch (cause) {
    if (current(captured)) error.value = cause.message || 'Git 连接操作失败'
  } finally {
    if (current(captured)) { clearSecrets(); busy.value = false }
  }
}
function create() {
  if (!canCreate.value) return
  const payload = { ...form, provider: 'gitea', request_id: crypto.randomUUID() }
  return mutate(() => gitApi.createConnection(payload))
}
function update(item) {
  if (!credentialToken.value.trim()) return
  const token = credentialToken.value
  return mutate(() => gitApi.updateCredential(item.id, token))
}
function beginEdit(item) { clearSecrets(); editingId.value = item.id; error.value = ''; success.value = '' }
function cancelEdit() { clearSecrets(); editingId.value = '' }
watch(() => user.uid, () => {
  generation++; loadSequence++; clearSecrets(); connections.value = []; busy.value = false; loading.value = false
  error.value = ''; success.value = ''; creating.value = false; editingId.value = ''
  Object.assign(form, { name: '', api_origin: '', ssh_host: '', ssh_port: 22, ssh_known_host_key: '', api_token: '' })
  if (props.active) void load()
}, { immediate: true })
watch(() => props.active, active => { clearSecrets(); if (active) { error.value = ''; void load() } })
onBeforeUnmount(() => { generation++; clearSecrets() })
</script>

<template>
  <section class="git-connections-settings" aria-label="我的 Git 连接">
    <header class="connections-heading"><div><h2>Git 连接</h2><p>管理你的 Git 服务地址和凭据，供各项目选择使用。</p></div><div class="connections-actions"><a-button :disabled="busy" :loading="loading" aria-label="刷新 Git 连接" @click="error = ''; load()"><RefreshCw :size="16" /></a-button><a-button type="primary" :disabled="busy" @click="creating = !creating; clearSecrets()"><Plus :size="16" />添加连接</a-button></div></header>
    <a-alert v-if="error" type="error" show-icon :message="error" />
    <a-alert v-if="success" type="success" show-icon :message="success" />
    <a-form v-if="creating" layout="vertical" class="connection-form" :disabled="busy" @finish="create">
      <div class="connection-fields"><a-form-item label="连接名称" required><a-input v-model:value="form.name" aria-label="连接名称" placeholder="例如：公司 Gitea" /></a-form-item><a-form-item label="服务地址（API Origin）" required><a-input v-model:value="form.api_origin" aria-label="Git 服务地址" placeholder="https://gitea.example.com" /></a-form-item><a-form-item label="SSH Host" required><a-input v-model:value="form.ssh_host" aria-label="SSH Host" /></a-form-item><a-form-item label="SSH Port" required><a-input-number v-model:value="form.ssh_port" :min="1" :max="65535" aria-label="SSH Port" /></a-form-item></div>
      <a-form-item label="SSH known-host key" required><a-textarea v-model:value="form.ssh_known_host_key" :rows="2" aria-label="SSH known-host key" /></a-form-item><a-form-item label="Gitea API Token" required><a-input-password v-model:value="form.api_token" autocomplete="new-password" aria-label="Gitea API Token" /><p class="connection-help">Token 仅用于本次提交，不会从服务器回显。</p></a-form-item><div class="connections-actions"><a-button :disabled="busy" @click="creating = false; clearSecrets()">取消</a-button><a-button type="primary" html-type="submit" :loading="busy" :disabled="!canCreate">创建连接</a-button></div>
    </a-form>
    <a-spin :spinning="loading"><div class="connection-list"><article v-for="item in connections" :key="item.id" class="connection-card"><div class="connection-identity"><GitBranch :size="22" /><div><h3>{{ item.name }}</h3><p>{{ item.api_origin }}</p><small>{{ item.ssh_host }}:{{ item.ssh_port }} · {{ item.provider }}</small></div></div><div class="connections-actions"><a-tag>{{ item.status === 'active' ? '可用' : '已停用' }}</a-tag><a-button :disabled="busy || item.status !== 'active'" @click="beginEdit(item)">更新 Token</a-button><a-popconfirm title="删除此连接？正在被项目仓库使用的连接无法删除。" :disabled="busy" @confirm="mutate(() => gitApi.deleteConnection(item.id))"><a-button danger :disabled="busy">删除</a-button></a-popconfirm></div><div v-if="editingId === item.id" class="credential-form"><label :for="`git-token-${item.id}`">新的 Gitea API Token</label><a-input-password :id="`git-token-${item.id}`" v-model:value="credentialToken" :disabled="busy" autocomplete="new-password" /><div class="connections-actions"><a-button :disabled="busy" @click="cancelEdit">取消</a-button><a-button type="primary" :loading="busy" :disabled="!credentialToken.trim()" @click="update(item)">保存 Token</a-button></div></div></article></div><a-empty v-if="!loading && !connections.length" description="还没有 Git 连接" /></a-spin>
  </section>
</template>

<style scoped lang="less">
.git-connections-settings { display:grid; gap:20px; color:var(--color-text); }
.connections-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; h2 { font-size:20px; margin:0 0 6px; } p { font-size:13px; color:var(--color-text-secondary); margin:0; } }
.connections-actions { display:flex; gap:8px; align-items:center; flex-wrap:wrap; :deep(.ant-btn) { display:inline-flex; align-items:center; gap:6px; } }
.connection-form,.connection-card { background:var(--gray-0); border:1px solid var(--gray-150); border-radius:10px; padding:20px; }
.connection-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:0 16px; }
.connection-list { display:grid; gap:14px; }.connection-card { display:flex; flex-wrap:wrap; gap:18px; justify-content:space-between; align-items:center; }
.connection-identity { display:flex; gap:12px; align-items:flex-start; min-width:0; flex:1; >svg { color:var(--main-color); flex-shrink:0; margin-top:3px; } >div { min-width:0; } h3 { font-size:16px; margin:0 0 5px; } p,small { color:var(--color-text-secondary); overflow-wrap:anywhere; margin:0; } small { font-size:12px; } }
.credential-form { flex-basis:100%; display:grid; gap:10px; padding-top:16px; border-top:1px solid var(--gray-150); label { font-size:13px; } }
.connection-help { color:var(--color-text-secondary); font-size:12px; margin:8px 0 0; }
@media(max-width:600px) { .connections-heading { flex-direction:column; }.connection-fields { grid-template-columns:minmax(0,1fr); }.connection-card { padding:16px; }.connection-identity { flex-basis:100%; } }
</style>
