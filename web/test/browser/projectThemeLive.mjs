/* global process */
import assert from 'node:assert/strict'
import { Buffer } from 'node:buffer'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import path from 'node:path'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fixture = JSON.parse(await readFile(process.env.THEME_EVIDENCE_SESSION, 'utf8'))
const api = process.env.THEME_EVIDENCE_API || 'http://127.0.0.1:15065'
const web = process.env.THEME_EVIDENCE_WEB || 'http://localhost:5173'
const out = path.resolve(process.env.THEME_EVIDENCE_OUTPUT)
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const checks = [], requests = [], errors = []
let stage = 'setup', delayed, fileEvidence
const check = (value, title) => { assert.ok(value, title); checks.push(title) }
const project = fixture.projects[0], second = fixture.projects[1]
const surveyPath = path.join(path.dirname(process.env.THEME_EVIDENCE_SESSION), 'shared', project.uid, 'workspace', project.workdir_path, 'survey.json')
const originalSurvey = Buffer.from(JSON.stringify({ project: project.name, samples: 12 }))
const headers = { Authorization: `Bearer ${fixture.users[0].token}` }
const execute = promisify(execFile)
async function mutateSurvey(action, content = Buffer.alloc(0)) {
  await execute('docker', ['exec', 'yuanlei-s05-evidence', 'python', '-m', 'test.e2e.mutate_project_theme_file', action, content.toString('base64')])
}
async function http(method, url, data, identity = headers) {
  const r = await page.request.fetch(api + url, { method, headers: identity, data })
  assert.ok(r.ok(), `${method} ${url} ${r.status()} ${await r.text()}`)
  return r.json()
}
const button = name => name === '重新读取' ? page.locator('.theme-status').getByRole('button', { name, exact: true }) : page.getByRole('button', { name, exact: true })
const files = ['web/src/apis/project_theme_api.js', 'web/src/components/project/themes/ThemeHost.vue', 'web/src/components/project/ProjectThemePanel.vue', 'web/src/utils/projectThemeReturn.js', 'backend/package/yuxi/services/project_theme_service.py', 'backend/package/yuxi/services/governance_service.py', 'backend/package/yuxi/repositories/governance_repository.py', 'backend/package/yuxi/repositories/project_work_repository.py', 'backend/package/yuxi/services/project_work_service.py', 'backend/server/routers/project_theme_router.py', 'backend/server/routers/governance_router.py', 'backend/server/routers/project_work_router.py', 'web/src/apis/governance_board_api.js', 'web/src/apis/project_work_api.js', 'web/src/components/project/themes/blocks/RecordsBlock.vue', 'web/src/components/project/themes/blocks/DiscussionBlock.vue', 'web/src/components/project/themes/ThemeBlockFrame.vue', 'web/src/components/project/ProjectThemeSelection.vue', 'web/src/views/ProjectDashboardView.vue', 'web/src/views/ProjectInspectionBoardView.vue', 'web/src/views/ProjectWorkTaskView.vue', 'backend/test/e2e/mutate_project_theme_file.py', 'backend/test/e2e/seed_project_theme_live.py', 'web/test/browser/projectThemeLive.mjs']
const hashes = async () => Object.fromEntries(await Promise.all(files.map(async file => [file, createHash('sha256').update(await readFile(file)).digest('hex')])))
const frozen = await hashes()
await mkdir(out, { recursive: true })
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(token => { if (!localStorage.getItem('user_token')) localStorage.setItem('user_token', token) }, fixture.users[0].token)
// 平台每个HTTP请求转发到隔离真实路由，保留状态和字节；延迟仅用于乱序负例。
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url())
  const response = await page.request.fetch(api + url.pathname + url.search, { method: request.method(), headers: request.headers(), data: request.postDataBuffer() || undefined })
  requests.push({ path: url.pathname, query: url.search, method: request.method(), status: response.status() })
  if (delayed?.matches(url)) { delayed.seen(); await delayed.release }
  try { await route.fulfill({ response }) } catch { /* 产品取消已发出的真实读取时，不将取消改成新结果。 */ }
})
try {
  await mutateSurvey('write', originalSurvey)
  const base = `/api/projects/${project.id}`
  const catalog = await http('GET', '/api/theme-sources')
  const variants = {}
  for (const source of catalog.sources.filter(s => s.kind === 'builtin')) {
    const pack = await http('GET', `/api/theme-versions/${source.versions[0].id}`)
    variants[pack.theme.id] = { source, version: source.versions[0], pack }
  }
  const topics = (await http('GET', base + '/governance/topics-page?limit=100')).items
  for (let index = topics.length; index < 24; index++) topics.push(await http('POST', base + '/governance/topics', { title: `S05真实课题 ${String(index).padStart(2, '0')}`, summary: '原业务HTTP创建，精确归属当前项目', source_channel: 'project' }))
  if (topics[0].admission_status === 'proposed') await http('POST', base + `/governance/topics/${topics[0].id}/review`, { approve: true })
  if (!(await http('GET', base + `/governance/topics/${topics[0].id}/comments-page`)).items.some(item => item.content === 'S05准确议题讨论，不能串对象')) await http('POST', base + `/governance/topics/${topics[0].id}/comments`, { content: 'S05准确议题讨论，不能串对象' })
  const otherTopic = (await http('GET', `/api/projects/${second.id}/governance/topics-page?limit=100`)).items[0] || await http('POST', `/api/projects/${second.id}/governance/topics`, { title: 'S05第二项目独立课题', source_channel: 'project' })
  const decision = (await http('GET', base + '/governance/decisions-page?limit=100')).items.find(item => item.title === 'S05真实已批准决定') || await http('POST', base + '/governance/decisions', { title: 'S05真实已批准决定', conclusion: '仅开展限定范围验证', topic_id: topics[0].id })
  const approved = decision.status === 'approved' ? decision : await http('POST', base + `/governance/decisions/${decision.id}/operations`, { action: 'approve', expected_revision: decision.revision_number, reason: 'S05合成业务验证依据' })
  await http('PUT', base + '/work/code', { code: 'S05' })
  await http('PUT', base + `/work/topics/${topics[0].id}/code`, { code: 'RES' })
  const work = (await http('GET', base + '/work/tasks-page?limit=100')).items.find(item => item.title === 'S05正式验证工作') || await http('POST', base + '/work/tasks', { title: 'S05正式验证工作', topic_id: topics[0].id, source_decision_id: decision.id, review_confirmed: true })
  const suggestion = (await http('GET', base + '/governance/board')).governance.tasks.find(item => item.title === 'S05未纳入工作建议') || await http('POST', base + '/governance/tasks', { title: 'S05未纳入工作建议', topic_id: topics[0].id })
  if ((await http('GET', `/api/projects/${second.id}/theme`)).generation === 0) await http('PUT', `/api/projects/${second.id}/theme`, { version_id: variants.research.version.id, expected_generation: 0, files: { survey: '/survey.json' } })
  for (const [endpoint, status] of [['/governance/topics-page', 'closed'], ['/work/tasks-page', 'done']]) {
    const filtered = await http('GET', base + endpoint + `?statuses=${status}`)
    check(filtered.items.length === 0 && filtered.pagination.total === 0, '隔离运行进程实际执行分页前状态过滤：' + status)
  }
  stage = 'choose-default'
  await page.goto(`${web}/projects?tab=themes&project_id=${project.id}&theme_action=select`)
  await page.getByLabel('主题发布版本').click()
  await page.getByText(`${variants.default.source.name} · ${variants.default.version.version} · 内置`, { exact: true }).last().click()
  await button('保存项目选择').click()
  await page.locator('[data-block="counts"][data-state="ready"]').waitFor()
  check((await page.locator('.theme-host').innerText()).includes('24'), '实际选择默认主题，摘要显示24个真实议题')
  check(!(await page.locator('.theme-host').innerText()).includes(suggestion.title), '工作建议不混入正式任务')
  check(await page.locator('[data-state="error"]').count() === 0, '默认Dashboard全部真实binding正常')
  await page.screenshot({ path: path.join(out, 'default-dashboard-light-1440.png'), fullPage: true })
  stage = 'task-operation-return'
  await page.locator(`[data-object-key="workTask:${work.id}"]`).click()
  await page.locator('.work-task-heading h1').waitFor()
  await page.getByText('来源、执行历史与工作管理', { exact: true }).click()
  check((await page.locator('.work-task-content').innerText()).includes(`版本 ${approved.revision_number}`), '原正式任务页保留准确冻结来源版本')
  await http('PATCH', base + `/work/tasks/${work.id}`, { status: 'todo' })
  await page.reload(); await page.locator('.work-task-heading h1').waitFor(); await page.getByText('来源、执行历史与工作管理', { exact: true }).click()
  await page.locator('.work-task-controls .ant-select-selector').first().click()
  await page.locator('.ant-select-item-option').filter({ hasText: '进行中' }).click()
  await button('保存状态').click()
  await page.waitForFunction(() => document.querySelector('.work-task-status')?.textContent.includes('进行中'))
  check((await http('GET', base + `/work/tasks/${work.id}`)).status === 'in_progress', '原页面办理状态并由真实HTTP回读')
  await button('返回项目主题').click()
  await page.locator('[data-block="attention"][data-state="ready"]').waitFor()
  check((await page.locator('[data-block="attention"]').innerText()).includes('进行中'), '返回同一主题Dashboard并刷新实际任务状态')
  stage = 'discussion-exact-topic'
  await button('工作台').click()
  await page.locator('[data-block="discussion"][data-state="ready"]').waitFor()
  check((await page.locator('[data-block="discussion"]').innerText()).includes('S05准确议题讨论'), '默认工作台读取准确已选议题讨论')
  await page.locator(`[data-select="${topics[1].id}"]`).click()
  await page.locator('[data-block="discussion"][data-state="empty"]').waitFor()
  check((await page.locator('[data-block="discussion"]').innerText()).includes(topics[1].title) && !(await page.locator('[data-block="discussion"]').innerText()).includes('S05准确议题讨论'), '切议题读取该议题真实空讨论，不串上一对象')
  await page.locator(`[data-select="${topics[0].id}"]`).click()
  await page.locator('[data-block="discussion"][data-state="ready"]').waitFor()
  stage = 'topic-page-return'
  await button('议题列表').click()
  await page.getByLabel('搜索议题标题').fill('23')
  await page.waitForFunction(() => document.querySelector('.theme-table tbody')?.textContent.includes('S05真实课题 23') && document.querySelectorAll('.theme-table tbody tr').length === 1)
  await page.locator('.theme-content').evaluate(node => { node.scrollTop = 150 })
  const scroll = await page.locator('.theme-content').evaluate(node => node.scrollTop)
  await page.locator(`[data-object-key="topic:${topics[23].id}"]`).click()
  await page.locator('.inspection-page').waitFor()
  check(new URL(page.url()).searchParams.get('topic_id') === topics[23].id, '议题点击进入原准确对象页面')
  await button('返回项目主题').click()
  await page.getByLabel('搜索议题标题').waitFor()
  check(await page.getByLabel('搜索议题标题').inputValue() === '23', '返回保留主题页面及搜索条件')
  await page.waitForFunction(value => document.querySelector('.theme-content')?.scrollTop === value, scroll)
  check(true, '返回恢复宿主实际滚动位置')
  await page.getByLabel('搜索议题标题').fill('')
  await page.waitForFunction(() => document.querySelectorAll('.theme-table tbody tr').length === 20)
  await button('下一页').click()
  await page.waitForFunction(() => document.querySelectorAll('.theme-table tbody tr').length === 4)
  check((await page.locator('.theme-table tbody').innerText()).includes('S05真实课题 23'), '议题真实分页可读后续记录')
  stage = 'research-selection'
  await page.getByRole('link', { name: '选择 / 更换主题', exact: true }).click()
  await page.getByLabel('主题发布版本').click()
  await page.getByText(`${variants.research.source.name} · ${variants.research.version.version} · 内置`, { exact: true }).last().click()
  await page.getByLabel('文件绑定 survey').fill('/survey.json')
  await button('保存项目选择').click()
  await page.locator('[data-block="question"][data-state="ready"]').waitFor()
  check((await page.locator('[data-block="question"]').innerText()).includes(topics[0].title), '同一真实项目选择调研主题，组织不同而议题身份一致')
  await button('证据资料').click()
  await page.locator('[data-block="survey"][data-state="ready"]').waitFor()
  check((await page.locator('[data-block="survey"]').innerText()).includes(project.name), '项目指定JSON来自当前Project Workdir')
  await page.waitForFunction(() => document.querySelector('.theme-image img')?.naturalWidth > 0)
  check(true, '授权包内PNG真实字节在浏览器解码')
  await page.screenshot({ path: path.join(out, 'research-evidence-light-1440.png'), fullPage: true })
  stage = 'file-refresh-errors'
  const modified = Buffer.from(JSON.stringify({ project: project.name, samples: 35 }))
  await mutateSurvey('write', modified)
  await button('重新读取').click()
  await page.waitForFunction(() => document.querySelector('[data-block="survey"]')?.textContent.includes('35'))
  const selection = await http('GET', base + '/theme')
  const fileResponse = await page.request.get(api + base + `/theme/files?alias=survey&expected_generation=${selection.generation}`, { headers })
  const actual = await fileResponse.body()
  fileEvidence = { projectId: project.id, generation: selection.generation, alias: 'survey', sha256: fileResponse.headers()['x-theme-sha256'], size: actual.length, mediaType: fileResponse.headers()['content-type'] }
  check(actual.equals(await readFile(surveyPath)) && fileResponse.headers()['x-theme-sha256'] === createHash('sha256').update(actual).digest('hex'), '修改文件后刷新，真实HTTP字节与独立文件及指纹一致')
  await mutateSurvey('missing')
  await button('重新读取').click()
  await page.locator('[data-block="survey"][data-state="missing"]').waitFor()
  check(!(await page.locator('[data-block="survey"]').innerText()).includes('35'), '缺文件明确missing，清除旧资料')
  await mutateSurvey('write', Buffer.from('not-json'))
  await button('重新读取').click()
  await page.locator('[data-block="survey"][data-state="error"]').waitFor()
  check(true, '实际文件类型错误可理解且不冒充空资料')
  await mutateSurvey('symlink')
  await button('重新读取').click()
  await page.locator('.project-theme-panel .ant-alert-message').filter({ hasText: '指定项目文件无权读取' }).waitFor()
  check(await page.locator('.theme-host').count() === 0, '符号链接拒绝已完成而非刷新加载中')
  check(!(await page.locator('.project-theme-panel').innerText()).includes(project.name), '符号链接拒绝并清空旧主题内容')
  await mutateSurvey('write', modified)
  const restoredFile = await page.request.get(api + base + `/theme/files?alias=survey&expected_generation=${selection.generation}`, { headers })
  check(restoredFile.ok() && (await restoredFile.body()).equals(modified), '恢复后的文件先由独立HTTP字节读确认')
  await button('重新读取').click()
  await page.locator('.theme-host').waitFor()
  await button('证据资料').click()
  await page.locator('[data-block="survey"][data-state="ready"]').waitFor()
  check((await page.locator('[data-block="survey"]').innerText()).includes('35'), '文件恢复后显式重读恢复真实资料')
  stage = 'decision-return'
  await button('研究结论').click()
  await page.locator(`[data-object-key="decision:${decision.id}"]`).click()
  await page.locator('.decision-detail').waitFor()
  check(new URL(page.url()).searchParams.get('decision_id') === decision.id, '决定进入原准确可信详情')
  await button('返回项目主题').click()
  await page.locator('[data-block="conclusions"][data-state="ready"]').waitFor()
  check(await page.locator('.theme-page-navigation button[aria-current="page"]').innerText() === '研究结论', '原决定页返回调研主题原页面')
  stage = 'switch-version-late-response'
  let seenVersion, releaseVersion
  const versionSeen = new Promise(resolve => { seenVersion = resolve }), versionRelease = new Promise(resolve => { releaseVersion = resolve })
  delayed = { matches: url => url.pathname === base + '/governance/topics-page', seen: seenVersion, release: versionRelease, cancel: releaseVersion }
  await button('课题脉络').click(); await versionSeen
  const beforeSwitch = await http('GET', base + '/theme')
  await http('PUT', base + '/theme', { version_id: variants.default.version.id, expected_generation: beforeSwitch.generation, files: {} })
  await button('重新读取').click()
  await page.locator('[data-block="counts"][data-state="ready"]').waitFor()
  releaseVersion(); delayed = undefined
  check(await button('Dashboard').count() === 1 && await button('课题脉络').count() === 0, '换真实绑定版本后旧响应不能恢复调研主题内容')
  stage = 'switch-project-late-response'
  let seenOld, releaseOld
  const seen = new Promise(resolve => { seenOld = resolve }), release = new Promise(resolve => { releaseOld = resolve })
  delayed = { matches: url => url.pathname === base + '/governance/topics-page', seen: seenOld, release, cancel: releaseOld }
  await button('议题列表').click(); await seen
  await page.goto(`${web}/projects/${second.id}/dashboard?view=theme`)
  await page.locator('[data-block="question"][data-state="ready"]').waitFor()
  releaseOld(); delayed = undefined
  check((await page.locator('.theme-host').innerText()).includes(otherTopic.title) && !(await page.locator('.theme-host').innerText()).includes(topics[0].title), '迟到真实旧项目响应不能覆盖新项目')
  stage = 'small-dark'
  await page.setViewportSize({ width: 375, height: 900 })
  await page.evaluate(() => localStorage.setItem('theme', 'dark'))
  await page.reload()
  await page.locator('[data-block="question"][data-state="ready"]').waitFor()
  check(await page.locator('html').evaluate(node => node.classList.contains('dark')), '深色模式由原平台主题store实际启用')
  await page.screenshot({ path: path.join(out, 'research-context-dark-375.png'), fullPage: true })
  check(await page.locator('.theme-host').evaluate(node => node.scrollWidth <= node.clientWidth + 1), '真实调研主题375px无宿主横向溢出')
  const finalBinding = await http('GET', base + '/theme')
  await http('PUT', base + '/theme', { version_id: variants.research.version.id, expected_generation: finalBinding.generation, files: { survey: '/survey.json' } })
  stage = 'permission-revoked'
  await page.evaluate(token => localStorage.setItem('user_token', token), fixture.users[1].token)
  await page.goto(`${web}/projects/${project.id}/dashboard?view=theme`)
  await page.locator('.project-theme-panel .ant-alert-message').filter({ hasText: '项目不存在或已无权访问' }).waitFor()
  check(await page.locator('.theme-host').count() === 0, '失权错误已完成读取且不保留旧宿主')
  check(!(await page.locator('.project-theme-panel').innerText()).includes(topics[0].title), '切换为另一真实账号后无权Project清空旧业务')
  check(errors.length === 0, '浏览器脚本错误0')
  assert.deepEqual(await hashes(), frozen, '验证期间源码保持冻结')
  await writeFile(path.join(out, 'browser-receipt.json'), JSON.stringify({ baseline: '3c996109', checks, requests, errors, sourceHashes: frozen, fileEvidence, objects: { projectId: project.id, secondProjectId: second.id, topicId: topics[0].id, selectedTopicId: topics[23].id, decisionId: decision.id, workTaskId: work.id } }, null, 2) + '\n')
  console.log(JSON.stringify({ checks: checks.length, requests: requests.length, errors: errors.length }))
} catch (error) {
  await mutateSurvey('write', originalSurvey)
  await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true })
  console.error(JSON.stringify({ stage, error: error.message, errors, failedRequests: requests.filter(r => r.status >= 400) }))
  throw error
} finally { delayed?.cancel(); await page.unrouteAll({ behavior: 'wait' }); await browser.close() }
