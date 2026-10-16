import assert from 'node:assert/strict'
import test from 'node:test'
import { baseWorkspacePages, resolveWorkspacePages, routeCapability, legacyThemeTarget } from '../../src/components/project/themes/workspaceCapabilities.js'
import { projectWorkspaceIntent } from '../../src/utils/projectWorkspaceIntent.js'

test('旧展示书签在能力主题进入真实消费者，旧ABI1仍保留展示', () => {
  const route = { params: { project_id: 'p' }, query: { theme_page: 'questions', decision_id: 'd' }, hash: '#decisions' }
  const pack = { manifest: { componentAbi: 2 }, theme: { pages: [{ id: 'questions', capability: 'topics' }] } }
  assert.deepEqual(legacyThemeTarget(pack, route), { name: 'ProjectTopics', params: { project_id: 'p' }, query: route.query, hash: '#decisions' })
  assert.equal(legacyThemeTarget({ ...pack, manifest: { componentAbi: 1 } }, route), null)
  assert.equal(legacyThemeTarget(pack, { ...route, query: {} }).name, 'ProjectDashboardComp')
  const mixed = { ...pack, theme: { pages: [...pack.theme.pages, { id: 'read-only', blocks: [{ id: 'brief', type: 'text' }] }] } }
  assert.equal(legacyThemeTarget(mixed, { ...route, query: { theme_page: 'read-only' } }), null)
  assert.equal(legacyThemeTarget(mixed, { ...route, query: { theme_page: 'unknown' } }), null)
})

test('第三主题独立ID、顺序和局部覆盖；缺失能力在同壳继承基础版本', () => {
  const pack={theme:{pages:[{id:'evidence-first',title:'先核证据',capability:'files',layout:'reading'},{id:'research-body',title:'研究正文',capability:'topics',layout:'reading'}]}}
  const pages=resolveWorkspacePages(pack)
  assert.equal(pages.length,9)
  assert.deepEqual(pages.slice(0,2).map(page=>[page.id,page.route,page.inherited]),[['evidence-first','ProjectFiles',false],['research-body','ProjectTopics',false]])
  assert.equal(pages.find(page=>page.capability==='blueprints').inherited,true)
  assert.deepEqual(new Set(pages.map(page=>page.capability)),new Set(baseWorkspacePages.map(page=>page.capability)))
  assert.equal(routeCapability('ProjectWorkTaskView'),'work')
  assert.equal(routeCapability('ProjectAgentWorkbenchView'),'agents')
})
test('历史URL转到准确主题业务视图，修订、评论、计划身份和hash保持', () => {
  for(const [query,hash,name] of [[{topic_id:'topic-a',revision:'3',comment_id:'reply-1'},'#comment-reply-1','ProjectTopics'],[{decision_id:'decision-a',decision_revision:'2'},'#decisions','ProjectTopics'],[{task_id:'suggestion-a'},'#task-suggestion-a','ProjectPlans'],[{},'#blueprint','ProjectBlueprints'],[{},'#reports','ProjectReports']]) {
    const result=projectWorkspaceIntent({params:{project_id:'project-a'},query,hash})
    assert.equal(result.name,name);assert.deepEqual(result.query,query);assert.equal(result.hash,hash);assert.equal(result.params.project_id,'project-a')
    assert.notEqual(result.name,'ProjectInspectionBoardComp')
  }
})

test('编辑进入主题明确设置能力，不按名称猜测或误入继承页', async () => {
  const { projectThemeSettingsTarget } = await import('../../src/components/project/themes/workspaceCapabilities.js')
  assert.deepEqual(projectThemeSettingsTarget('project', {theme:{pages:[{id:'manage-settings',capability:'settings'}]}}), {name:'ProjectSettings',params:{project_id:'project'},query:{theme_page:'manage-settings'}})
  assert.equal(projectThemeSettingsTarget('project', {theme:{pages:[{id:'settings',title:'设置'}]}}), null)
  assert.equal(projectThemeSettingsTarget('project', null), null)
})

test('显式隐藏只缩小主导航；缺页继承与准确业务入口保留', async () => {
  const { workspaceNavigationPages } = await import('../../src/components/project/themes/workspaceCapabilities.js')
  const pack = { theme: { hiddenCapabilities: ['plans','work','inspection','files','agents','settings'], pages: [{id:'focus-home',title:'总览',capability:'overview'}] } }
  assert.deepEqual(workspaceNavigationPages(pack).map(page => page.capability), ['overview','blueprints','topics'])
  assert.equal(resolveWorkspacePages(pack).find(page => page.capability === 'work').route, 'ProjectWorkTasksView')
  delete pack.theme.hiddenCapabilities
  assert.equal(workspaceNavigationPages(pack).length, 9)
})

test('默认与无包应急使用相同九项基础导航，不给应急额外继承徽标', () => {
  const current = {theme:{pages:baseWorkspacePages.map(page => ({...page,layout:page.capability==='overview'?'overview':'full'}))}}
  const baseline = pages => pages.map(({capability,title,group,route,inherited}) => ({capability,title,group,route,inherited}))
  assert.deepEqual(baseline(resolveWorkspacePages(current)),baseline(resolveWorkspacePages(null)))
  assert.equal(resolveWorkspacePages({theme:{pages:[]}}).filter(page=>page.inherited).length,9)
})
