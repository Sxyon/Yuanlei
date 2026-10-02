<template>
  <div class="inbox-page">
    <PageHeader title="收件箱" :loading="loading" show-border>
      <template #actions>
        <a-button size="small" :disabled="loading" @click="load">刷新</a-button>
      </template>
    </PageHeader>

    <main class="inbox-content">
      <nav class="inbox-folders" aria-label="收件箱分类">
        <button
          v-for="choice in folders"
          :key="choice.value"
          type="button"
          :class="{ active: folder === choice.value }"
          :aria-current="folder === choice.value ? 'page' : undefined"
          @click="folder = choice.value"
        >
          {{ choice.label }}
        </button>
      </nav>

      <a-spin v-if="loading" class="inbox-state" />
      <a-alert v-else-if="error" type="error" show-icon :message="error">
        <template #action><a-button size="small" @click="load">重试</a-button></template>
      </a-alert>
      <a-empty v-else-if="items.length === 0" description="这里还没有通知" />
      <ul v-else class="inbox-list">
        <li v-for="item in items" :key="item.id" class="inbox-item">
          <div class="inbox-item-main">
            <span class="inbox-kind">{{ kindInfo(item.kind).label }}</span>
            <h2>{{ item.title }}</h2>
            <p v-if="item.summary">{{ item.summary }}</p>
            <ol v-if="occurrencesFor(item).length > 1" class="inbox-occurrences">
              <li v-for="(occurrence, index) in occurrencesFor(item)" :key="index">
                <time :datetime="occurrence.at">{{ formatTime(occurrence.at) }}</time>
                <span>{{ occurrence.summary || '（无说明）' }}</span>
              </li>
            </ol>
            <time :datetime="item.created_at">{{ formatTime(item.created_at) }}</time>
          </div>
          <div class="inbox-actions">
            <a-button size="small" type="primary" :loading="busyId === item.id" @click="openItem(item)">
              {{ kindInfo(item.kind).action }}
            </a-button>
            <a-button size="small" :disabled="busyId === item.id" @click="changeItem(item, { read: !item.read_at })">
              {{ item.read_at ? '标为未读' : '标为已读' }}
            </a-button>
            <a-button size="small" :disabled="busyId === item.id" @click="changeItem(item, { archived: !item.archived_at })">
              {{ item.archived_at ? '移出归档' : '归档' }}
            </a-button>
          </div>
        </li>
      </ul>
      <a-button v-if="hasMore && !loading" class="inbox-more" :loading="loadingMore" @click="loadMore">
        加载更多
      </a-button>
      <p v-if="actionError" class="inbox-error" role="alert">{{ actionError }}</p>
    </main>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import PageHeader from '@/components/shared/PageHeader.vue'
import { inboxApi } from '@/apis/inbox_api'
import { agentApi } from '@/apis/agent_api'

const router = useRouter()
const folders = [
  { value: 'unread', label: '未读' },
  { value: 'read', label: '已读' },
  { value: 'archived', label: '归档' }
]
const folder = ref('unread')
const items = ref([])
const loading = ref(false)
const loadingMore = ref(false)
const hasMore = ref(false)
const busyId = ref(null)
const error = ref('')
const actionError = ref('')
const nextCursor = ref(null)
let loadVersion = 0

const formatTime = (value) => (value ? new Date(value).toLocaleString('zh-CN') : '')
const occurrencesFor = (item) => (Array.isArray(item.occurrences) ? item.occurrences : [])
const KIND_META = {
  task_completed: { label: '任务完成', action: '查看任务', target: 'task' },
  task_failed: { label: '任务失败', action: '查看任务', target: 'task' },
  task_interrupted: { label: '任务中断', action: '查看任务', target: 'task' },
  task_inspection: { label: '任务巡检', action: '查看任务', target: 'project_tasks' },
  run_question: { label: '等待答复', action: '前往答复', target: 'run' }
}
const kindInfo = (kind) => KIND_META[kind] || { label: kind, action: '查看来源', target: 'task' }

async function load() {
  const version = ++loadVersion
  const currentFolder = folder.value
  loading.value = true
  loadingMore.value = false
  error.value = ''
  try {
    const result = await inboxApi.list(currentFolder)
    if (version !== loadVersion) return
    items.value = result
    nextCursor.value = result.at(-1)?.id || null
    hasMore.value = result.length === 50
  } catch (cause) {
    if (version === loadVersion) error.value = cause?.message || '收件箱加载失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

async function loadMore() {
  const version = loadVersion
  loadingMore.value = true
  actionError.value = ''
  try {
    const result = await inboxApi.list(folder.value, nextCursor.value)
    if (version !== loadVersion) return
    const known = new Set(items.value.map((item) => item.id))
    items.value = [...items.value, ...result.filter((item) => !known.has(item.id))]
    if (result.length) nextCursor.value = result.at(-1).id
    hasMore.value = result.length === 50
  } catch (cause) {
    if (version === loadVersion) actionError.value = cause?.message || '更多通知加载失败'
  } finally {
    if (version === loadVersion) loadingMore.value = false
  }
}

async function changeItem(item, change) {
  busyId.value = item.id
  actionError.value = ''
  try {
    await inboxApi.update(item.id, change)
    await load()
  } catch (cause) {
    actionError.value = cause?.message || '通知更新失败'
  } finally {
    busyId.value = null
  }
}

async function openItem(item) {
  busyId.value = item.id
  actionError.value = ''
  try {
    let destination
    const target = kindInfo(item.kind).target
    if (target === 'task') {
      destination = `/projects/${encodeURIComponent(item.project_id)}/work/tasks/${encodeURIComponent(item.source_id)}`
    } else if (target === 'project_tasks') {
      destination = `/projects/${encodeURIComponent(item.project_id)}/work/tasks`
    } else {
      const response = await agentApi.getAgentRun(item.source_id)
      destination = `/agent/${encodeURIComponent(response.run.conversation_thread_id)}`
    }
    if (!item.read_at) await inboxApi.update(item.id, { read: true })
    await router.push(destination)
  } catch (cause) {
    actionError.value = cause?.message || '无法打开通知来源'
  } finally {
    busyId.value = null
  }
}

watch(folder, load, { immediate: true })
</script>

<style scoped lang="less">
.inbox-content { max-width: 920px; margin: 0 auto; padding: 24px; }
.inbox-folders { display: flex; gap: 8px; margin-bottom: 24px; }
.inbox-folders button { border: 1px solid var(--gray-150); background: var(--gray-0); color: var(--gray-700); border-radius: 8px; padding: 7px 16px; cursor: pointer; }
.inbox-folders button.active { color: var(--main-color); border-color: var(--main-color); background: var(--main-30); }
.inbox-state { display: block; margin: 56px auto; }
.inbox-list { list-style: none; margin: 0; padding: 0; }
.inbox-item { display: flex; justify-content: space-between; align-items: center; gap: 24px; padding: 20px 4px; border-bottom: 1px solid var(--gray-150); }
.inbox-item-main { min-width: 0; }
.inbox-kind { color: var(--main-color); font-size: 12px; }
.inbox-item h2 { margin: 5px 0; color: var(--gray-900); font-size: 16px; font-weight: 600; }
.inbox-item p { margin: 0 0 7px; color: var(--gray-700); overflow-wrap: anywhere; }
.inbox-occurrences { margin: 0 0 7px; padding-left: 18px; color: var(--gray-700); font-size: 13px; }
.inbox-occurrences li { margin-bottom: 2px; }
.inbox-occurrences time { margin-right: 8px; color: var(--gray-500); font-size: 12px; }
.inbox-item time { color: var(--gray-500); font-size: 12px; }
.inbox-actions { display: flex; flex-wrap: wrap; gap: 8px; flex-shrink: 0; }
.inbox-error { margin-top: 16px; color: var(--color-error-700); }
.inbox-more { display: block; margin: 24px auto; }
@media (max-width: 680px) { .inbox-item { display: block; } .inbox-actions { margin-top: 14px; } }
</style>
