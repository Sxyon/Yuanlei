<script setup>
import { computed, onUnmounted, ref, shallowRef, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { Palette, Sun, Moon } from '@lucide/vue'
import PageHeader from '@/components/shared/PageHeader.vue'
import ThemeHost from '@/components/project/themes/ThemeHost.vue'
import { bundledThemeCatalog, bundledThemeLoader } from '@/components/project/themes/bundledThemes'
import { createSyntheticAdapter, syntheticProjects } from '@/components/project/themes/syntheticAdapter'
import { createContextGate, validateThemePackage } from '@/components/project/themes/contract'
import { useUserStore } from '@/stores/user'
import { useThemeStore } from '@/stores/theme'

const user = useUserStore(), theme = useThemeStore()
const projectId = ref(syntheticProjects[0].id), themeId = ref(bundledThemeCatalog[0].id)
const bundle = shallowRef(null), loading = ref(false), error = ref('')
const scenario = ref('ready'), delayMs = ref(0), definitionCase = ref('valid'), refreshGeneration = ref(0)
const gate = createContextGate()
let controller
const project = computed(() => syntheticProjects.find(item => item.id === projectId.value))
const adapter = createSyntheticAdapter(bundledThemeLoader, () => ({ scenario: scenario.value, delayMs: delayMs.value, ignoreAbort: delayMs.value > 0 }))
const host = ref(null)

/** 仅在预览加载边界制造定义负例；合法样例和宿主不包含主题专用分支。 */
async function load() {
  controller?.abort(); controller = new AbortController()
  const token = gate.next({ userId: user.uid, projectId: projectId.value, themeId: themeId.value })
  loading.value = true; error.value = ''
  try {
    const value = await bundledThemeLoader.load({ selectionId: token.themeId, signal: controller.signal })
    if (!gate.isCurrent(token)) return
    if (definitionCase.value === 'unknown') value.theme.pages[0].blocks[0].type = 'unknown'
    if (definitionCase.value === 'binding') value.theme.pages[0].blocks[0].binding = { kind: 'business', resource: 'tasks' }
    if (definitionCase.value === 'version') value.manifest.componentAbi = 999
    validateThemePackage({ manifest: value.manifest, theme: value.theme })
    bundle.value = value
  } catch (cause) { if (gate.isCurrent(token)) { bundle.value = null; error.value = cause.message || '主题读取失败' } }
  finally { if (gate.isCurrent(token)) loading.value = false }
}
watch([projectId, themeId, definitionCase, refreshGeneration, () => user.uid], load, { immediate: true, flush: 'sync' })
watch([scenario, delayMs], () => { refreshGeneration.value++ })
onUnmounted(() => { gate.invalidate(); controller?.abort() })
</script>
<template>
  <section class="project-theme-preview">
    <PageHeader title="项目主题预览" show-border><template #actions><RouterLink :to="{ name: 'ProjectsComp', query: { tab: 'themes' } }">返回主题管理</RouterLink><a-button class="lucide-icon-btn" aria-label="切换明暗样式" @click="theme.toggleTheme()"><Sun v-if="theme.isDark" :size="16" /><Moon v-else :size="16" /></a-button></template></PageHeader>
    <p class="preview-banner" role="status">S03 独立预览 · 业务对象、讨论、文件和历史快照均为合成数据 · 无真实项目绑定、保存或批准。</p>
    <div class="preview-controls"><label>合成项目<select v-model="projectId" aria-label="选择合成项目"><option v-for="item in syntheticProjects" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><label>主题<select v-model="themeId" aria-label="选择主题"><option v-for="item in bundledThemeCatalog" :key="item.id" :value="item.id">{{ item.name }}</option></select></label><details class="preview-tools"><summary>验证状态与迟到响应</summary><div><label>合成响应<select v-model="scenario" aria-label="合成响应状态"><option value="ready">正常</option><option value="empty">空业务</option><option value="missing">缺文件</option><option value="unbound">未绑定</option><option value="denied">无权</option><option value="error">读取错误</option></select></label><label>数据延迟<select v-model.number="delayMs" aria-label="合成数据延迟"><option :value="0">无延迟</option><option :value="1200">1.2 秒，忽略取消以验证隔离</option></select></label><label>定义验例<select v-model="definitionCase" aria-label="主题定义验例"><option value="valid">合法定义</option><option value="unknown">未知组件</option><option value="binding">非法业务绑定</option><option value="version">不支持 ABI</option></select></label><a-button @click="refreshGeneration++">重新加载</a-button></div></details></div>
    <div v-if="loading" class="preview-state" role="status"><a-spin /><p>正在读取并校验主题包…</p></div>
    <div v-else-if="error" class="preview-state" role="alert"><h2>主题加载失败</h2><p>{{ error }}</p><a-button @click="load">重新读取</a-button><RouterLink :to="{ name: 'ProjectsComp', query: { tab: 'themes' } }">返回主题管理</RouterLink></div>
    <ThemeHost v-if="bundle" v-show="!loading && !error" ref="host" :key="`${user.uid}:${projectId}`" :theme-package="bundle" :project-id="projectId" :project-label="project.name" :user-id="String(user.uid)" :adapter="adapter" :binding-generation="refreshGeneration" :paused="loading || Boolean(error)" simulation>
      <template #platform-navigation><div class="preview-platform-links"><RouterLink :to="{ name: 'ProjectsComp' }">项目列表</RouterLink><RouterLink :to="{ name: 'ProjectsComp', query: { tab: 'themes' } }"><Palette :size="16" />主题管理</RouterLink><p>工作与资料办理在真实项目内进入；此处仅预览合成对象。</p></div></template>
    </ThemeHost>
  </section>
</template>
<style scoped lang="less">
.project-theme-preview { display: flex; flex-direction: column; height: 100%; min-width: 0; min-height: 0; background: var(--gray-0); color: var(--color-text); }
.preview-banner { margin: 0; padding: 10px 24px; background: var(--color-warning-50); color: var(--color-warning-900); font-size: 13px; }
.preview-controls { display: flex; flex-wrap: wrap; align-items: center; gap: 16px; padding: 16px 24px; border-bottom: 1px solid var(--gray-150); label { display: flex; align-items: center; gap: 8px; } select { max-width: 250px; min-width: 0; font: inherit; color: inherit; background: var(--gray-0); border: 1px solid var(--gray-150); border-radius: 6px; padding: 8px; } }
.preview-tools { margin-left: auto; font-size: 13px; summary { cursor: pointer; color: var(--color-text-secondary); } > div { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; } }
.preview-state { padding: 32px; min-width: 0; p { margin: 12px 0; overflow-wrap: anywhere; } a { display: inline-block; margin-left: 16px; } }
.preview-platform-links { margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--gray-150); p { font-size: 12px; padding: 12px; color: var(--color-text-secondary); } }
select:focus-visible, summary:focus-visible { outline: 2px solid var(--main-color); outline-offset: 3px; }
@media (max-width: 768px) { .preview-banner, .preview-controls { padding-left: 16px; padding-right: 16px; } .preview-controls { gap: 8px; label { flex-wrap: wrap; } } .preview-tools { margin-left: 0; width: 100%; } }
</style>
