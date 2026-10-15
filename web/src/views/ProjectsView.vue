<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { message } from 'ant-design-vue'
import { projectThemeApi } from '@/apis/project_theme_api'
import { validateLoadedPackage } from '@/components/project/themes/contract'
import { projectThemeSettingsTarget } from '@/components/project/themes/workspaceCapabilities'
import { useUserStore } from '@/stores/user'
import { Grid2X2, List, Plus, RefreshCw, SlidersHorizontal } from '@lucide/vue'
import ProjectThemeManager from '@/components/project/ProjectThemeManager.vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import ProjectCreateModal from '@/components/ProjectCreateModal.vue'
import ProjectSettingsModal from '@/components/ProjectSettingsModal.vue'
import FallbackAvatar from '@/components/common/FallbackAvatar.vue'
import { useProjectsStore } from '@/stores/projects'
import { projectTypes, formatRelativeTime } from '@/utils/projectSelection'
import { defaultProjectWidths, projectStatuses, searchManagedProjects } from '@/utils/projectManagement'

const route = useRoute(), router = useRouter(), store = useProjectsStore()
const { projects, isLoading, hasLoaded, error, management } = storeToRefs(store)
const tab = computed(() => route.query.tab === 'themes' ? 'themes' : 'projects')
const tabs = [{key: 'projects', label: '项目列表'}, {key: 'themes', label: '主题管理'}]
const filtered = computed(() => searchManagedProjects(projects.value, management.value.query))
const createOpen = ref(false), editing = ref(null), editingId = ref(null)
const user = useUserStore()
let editRequest = 0
/** 优先进入已绑定主题的设置页，未声明设置时沿用原弹窗。 */
async function editProject(project) {
  const request = ++editRequest, owner = user.uid
  editingId.value = project.id
  try {
    const selection = await projectThemeApi.binding(project.id)
    if (request !== editRequest || user.uid !== owner || route.name !== 'ProjectsComp') return
    if (selection.state === 'error') throw new Error(selection.error?.message || '项目主题不可用，请先修复绑定')
    const target = projectThemeSettingsTarget(project.id, selection.state === 'ready' ? validateLoadedPackage(selection.package) : null)
    if (target) await router.push(target)
    else editing.value = project
  } catch (cause) {
    if (request !== editRequest || user.uid !== owner || route.name !== 'ProjectsComp') return
    message.error(cause.message || '读取项目主题失败，请重试')
  } finally { if (request === editRequest) editingId.value = null }
}
const themeProjectId = computed(() => String(route.query.project_id || ''))
const columnNames = ['项目 / 描述', '类型 / 分类', '管理状态', '负责人', 'Workdir / 更新时间']
const columnMinimums = [240, 100, 100, 100, 100]
const tableWidth = computed(() => management.value.widths.reduce((sum, w) => sum + w, 100))
const typeLabel = p => projectTypes.find(t => t.value === p.project_type)?.label || '未指定'
const statusLabel = p => projectStatuses.find(t => t.value === p.work_status)?.label || '计划中'
const ownerLabel = p => p.owner_type === 'none' ? '无负责人' : p.owner_name || '负责人不可用'
const dashboard = p => ({name: 'ProjectDashboardComp', params: {project_id: p.id}})

/** 刷新失败由列表Owner保留旧数据并显示可重试状态。 */
async function reload() { try { await store.loadProjects() } catch { /* store保留错误及上次结果。 */ } }
async function created(project) { store.upsertProject(project); await reload() }
async function saved(project) { store.replaceProject(project); await reload() }
function changeTab(item) { router.replace({path: '/projects', query: {...route.query, tab: item.key}}) }
function selectThemeProject(value) { router.replace({path: '/projects', query: {tab: 'themes', ...(value ? {project_id: value} : {})}}) }
onMounted(reload)
</script>

<template>
  <div class="projects-view">
    <PageHeader title="项目" :tabs="tabs" :active-key="tab" :loading="isLoading" show-border aria-label="项目管理视图切换" @change="changeTab" />
    <main class="management-content">
      <a-alert v-if="error" type="error" show-icon :message="hasLoaded ? '项目刷新失败，当前显示上次读取的数据' : '项目加载失败'" class="state-alert">
        <template #action><a-button size="small" :loading="isLoading" @click="reload">重试</a-button></template>
      </a-alert>
      <template v-if="tab === 'projects'">
        <div class="project-toolbar">
          <span class="count" role="status">{{ hasLoaded ? `${filtered.length} 个项目${management.query ? '匹配搜索' : ''}` : isLoading ? '正在读取项目…' : '' }}</span>
          <a-input-search v-model:value="management.query" allow-clear class="project-search" placeholder="搜索名称、标识、描述、分类或标签" aria-label="搜索项目" />
          <a-popover v-if="management.view === 'list'" trigger="click" placement="bottomRight" title="调整列宽（当前会话）">
            <template #content><div class="width-controls">
              <label v-for="(name, index) in columnNames" :key="name">{{ name }} · {{ management.widths[index] }}px<a-slider v-model:value="management.widths[index]" :min="columnMinimums[index]" :max="index === 0 ? 600 : 320" :aria-label="`${name}列宽`" /></label>
              <a-button size="small" @click="management.widths = [...defaultProjectWidths]">恢复默认列宽</a-button>
            </div></template>
            <a-button><SlidersHorizontal :size="15" /></a-button>
          </a-popover>
          <div class="view-switch" role="group" aria-label="项目展示方式">
            <a-button :type="management.view === 'cards' ? 'primary' : 'default'" aria-label="卡片视图" :aria-pressed="management.view === 'cards'" @click="management.view = 'cards'"><Grid2X2 :size="16" /></a-button>
            <a-button :type="management.view === 'list' ? 'primary' : 'default'" aria-label="列表视图" :aria-pressed="management.view === 'list'" @click="management.view = 'list'"><List :size="16" /></a-button>
          </div>
          <a-button :loading="isLoading" aria-label="刷新项目" @click="reload"><RefreshCw :size="15" /></a-button>
          <a-button type="primary" @click="createOpen = true"><Plus :size="16" />新建项目</a-button>
        </div>
        <div v-if="isLoading && !hasLoaded" class="project-cards" aria-label="正在读取项目" aria-busy="true"><div v-for="i in 6" :key="i" class="project-card"><a-skeleton active :paragraph="{rows: 3}" /></div></div>
        <a-empty v-else-if="hasLoaded && !filtered.length" :description="management.query ? '没有匹配的项目' : '暂无项目'" class="empty-state">
          <a-button v-if="management.query" @click="management.query = ''">清除搜索</a-button>
          <a-button v-else type="primary" @click="createOpen = true">新建项目</a-button>
        </a-empty>
        <div v-else-if="hasLoaded && management.view === 'cards'" class="project-cards">
          <article v-for="project in filtered" :key="project.id" class="project-card">
            <div class="card-identity">
              <FallbackAvatar :src="project.icon" :name="project.name" :seed="project.id" kind="agent" shape="rounded" :size="40" decorative />
              <div><RouterLink :to="dashboard(project)" class="project-name" :title="project.name">{{ project.name }}</RouterLink><span v-if="project.slug" class="project-slug">{{ project.slug }}</span></div>
            </div>
            <p class="project-description" :title="project.description">{{ project.description || '暂无描述' }}</p>
            <div class="card-attributes"><span>{{ typeLabel(project) }}</span><span v-if="project.category" :title="project.category" class="category">{{ project.category }}</span><span class="status-tag">{{ statusLabel(project) }}</span></div>
            <footer><time :datetime="project.updated_at" :title="project.updated_at">更新于{{ formatRelativeTime(project.updated_at) || '未知' }}</time><a-button type="text" size="small" :loading="editingId === project.id" @click="editProject(project)" class="project-edit">编辑</a-button><RouterLink :to="dashboard(project)" class="entry-link">进入项目 →</RouterLink></footer>
          </article>
        </div>
        <div v-else-if="hasLoaded" class="table-scroll" role="region" aria-label="项目列表，可横向滚动" tabindex="0">
          <p class="table-hint">列表可横向滚动；窄屏可切换卡片视图。</p>
          <table class="project-table" :style="{minWidth: `${tableWidth}px`}">
            <colgroup><col v-for="(width, i) in management.widths" :key="i" :style="{width: `${width}px`}" /><col style="width:100px" /></colgroup>
            <thead><tr><th v-for="name in columnNames" :key="name" scope="col">{{ name }}</th><th scope="col">操作</th></tr></thead>
            <tbody><tr v-for="project in filtered" :key="project.id">
              <td><div class="table-identity"><FallbackAvatar :src="project.icon" :name="project.name" :seed="project.id" kind="agent" shape="rounded" :size="32" decorative /><div><RouterLink :to="dashboard(project)" class="project-name" :title="project.name">{{ project.name }}</RouterLink><span v-if="project.slug" class="project-slug">{{ project.slug }}</span><p class="table-description" :title="project.description">{{ project.description || '暂无描述' }}</p></div></div></td>
              <td>{{ typeLabel(project) }}<small>{{ project.category || '未分类' }}</small></td>
              <td><span class="status-tag">{{ statusLabel(project) }}</span></td><td>{{ ownerLabel(project) }}</td>
              <td><span class="workdir" :title="project.workdir_path">{{ project.workdir_path }}</span><small :title="project.updated_at">更新于{{ formatRelativeTime(project.updated_at) || '未知' }}</small></td>
                <td>
                  <div class="row-actions">
                    <a-button type="link" size="small" :loading="editingId === project.id" @click="editProject(project)">编辑</a-button>
                    <RouterLink :to="dashboard(project)" class="entry-link">进入</RouterLink>
                  </div>
                </td>
            </tr></tbody>
          </table>
        </div>
      </template>
      <ProjectThemeManager v-else :project-id="themeProjectId" :projects="projects" @project="selectThemeProject" />
    </main>
    <ProjectCreateModal v-model:open="createOpen" @created="created" />
    <ProjectSettingsModal :open="Boolean(editing)" :project="editing" initial-tab="description" @update:open="!$event && (editing = null)" @saved="saved" />
  </div>
</template>

<style scoped lang="less">
.projects-view { display: flex; flex-direction: column; min-height: 100%; min-width: 0; background: var(--gray-0); color: var(--color-text); }
.management-content { padding: 24px var(--page-padding); min-width: 0; }
.project-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 24px; :deep(.ant-btn) { display: inline-flex; align-items: center; justify-content: center; gap: 6px; } }
.count { margin-right: auto; font-size: 13px; color: var(--color-text-secondary); }
.project-search { width: 300px; }
.view-switch { display: flex; gap: 0; :deep(.ant-btn:first-child) { border-radius: 6px 0 0 6px; } :deep(.ant-btn:last-child) { border-radius: 0 6px 6px 0; } }
.project-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 380px), 1fr)); gap: 16px; }
.project-card { display: flex; flex-direction: column; min-width: 0; padding: 20px; border: 1px solid var(--gray-150); border-radius: 8px; background: var(--gray-0); }
.card-identity, .table-identity { display: flex; gap: 12px; align-items: flex-start; > div { min-width: 0; flex: 1; } }
.project-name { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; font-size: 15px; font-weight: 600; color: var(--color-text); line-height: 1.6; text-decoration: none; &:hover { color: var(--main-color); text-decoration: none; } }
.project-slug { display: block; overflow-wrap: anywhere; font-size: 12px; color: var(--color-text-secondary); margin-top: 4px; }
.project-description { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; min-height: 44px; font-size: 13px; color: var(--color-text-secondary); line-height: 1.7; margin: 16px 0; }
.card-attributes { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; font-size: 12px; color: var(--color-text-secondary); margin-bottom: 20px; .category { max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; } }
.status-tag { display: inline-block; padding: 2px 8px; border-radius: 12px; background: var(--gray-100); color: var(--gray-700); font-size: 12px; white-space: nowrap; }
footer { display: flex; align-items: center; gap: 8px; margin-top: auto; border-top: 1px solid var(--gray-100); padding-top: 12px; time { margin-right: auto; font-size: 12px; color: var(--color-text-secondary); } }
.project-edit { color: var(--main-color);}
.entry-link { font-size: 13px; white-space: nowrap; color: var(--main-color); text-decoration: none; &:hover { text-decoration: none; } }
.empty-state { padding: 64px 0; }
.state-alert { margin-bottom: 20px; }
.width-controls { width: 240px; label { display: block; color: var(--color-text-secondary); font-size: 12px; } }
.table-scroll { overflow-x: auto; border: 1px solid var(--gray-150); border-radius: 8px; }
.table-hint { color: var(--color-text-secondary); font-size: 12px; margin: 12px 16px; }
.project-table { width: 100%; table-layout: fixed; border-collapse: collapse; th { background: var(--gray-25); color: var(--gray-600); font-weight: 500; text-align: left; font-size: 12px; padding: 12px 16px; } td { border-top: 1px solid var(--gray-100); padding: 16px; font-size: 13px; overflow-wrap: anywhere; vertical-align: top; } small { display: block; margin-top: 6px; font-size: 12px; color: var(--color-text-secondary); } }
.table-description { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--color-text-secondary); margin: 6px 0 0; font-size: 12px; }
.row-actions { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; > a, :deep(.ant-btn) { display: inline-flex; align-items: center; justify-content: center; box-sizing: border-box; width: 44px; height: 24px; margin: 0; padding: 0; border: 1px solid transparent; font-size: 13px; line-height: 22px; color: var(--main-color); text-decoration: none; } }
.workdir { font-size: 12px; }
.theme-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-bottom: 24px; p { color: var(--color-text-secondary); margin: 0; } a { max-width: 55%; overflow-wrap: anywhere; } }
.theme-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.theme-location { border: 1px solid var(--gray-150); border-radius: 8px; padding: 24px; min-width: 0; > svg { color: var(--main-color); } h2 { font-size: 16px; margin: 12px 0; } p { font-size: 13px; color: var(--color-text-secondary); line-height: 1.8; overflow-wrap: anywhere; } dl { display: grid; grid-template-columns: 80px 1fr; gap: 12px; margin: 24px 0; font-size: 13px; dd { margin: 0; overflow-wrap: anywhere; } dt { color: var(--color-text-secondary); } } :deep(.ant-select) { width: 100%; } :deep(.ant-btn) { max-width: 100%; height: auto; white-space: normal; min-height: 32px; } }
@media (max-width: 700px) { .management-content { padding: 16px 12px; } .project-search { order: -1; width: 100%; } .count { flex-basis: 100%; } .theme-grid { grid-template-columns: 1fr; } }
</style>
