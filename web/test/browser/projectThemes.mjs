/* global process */
import assert from 'node:assert/strict'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'

// 真实Vue页面／DOM验证，认证和平台列表只在此测试浏览器中隔离；不写日常数据。
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const out = path.join(root, 'docs/元垒系统架构规划设计/图解/15-s03-implementation-20261012')
await mkdir(out, { recursive: true })
const base = process.env.S03_BASE_URL || 'http://127.0.0.1:5173'
const sources = ['web/src/views/ProjectThemePreviewView.vue', 'web/src/views/ProjectsView.vue', 'web/src/router/index.js', 'backend/package/yuxi/services/project_theme_contract.py']
async function collect(folder) {
  for (const item of await readdir(path.join(root, folder), { withFileTypes: true })) {
    const file = folder + '/' + item.name
    if (item.isDirectory()) await collect(file)
    else sources.push(file)
  }
}
await collect('web/src/components/project/themes')
const hashes = async () => Object.fromEntries(await Promise.all(sources.map(async file => [file, createHash('sha256').update(await readFile(path.join(root, file))).digest('hex')])))
const sourceHashes = await hashes()
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
const page = await context.newPage(), errors = [], writes = [], checks = [], urls = []
page.on('pageerror', e => errors.push(e.message))
page.on('request', r => { if (r.url().includes('/api/')) { urls.push(new URL(r.url()).pathname); if (r.method() !== 'GET') writes.push({ method: r.method(), path: new URL(r.url()).pathname }) } })
await context.addInitScript(() => { localStorage.setItem('user_token', 'synthetic-browser-only'); localStorage.setItem('theme', 'light') })
await context.addInitScript(() => {
  window.s03ActiveBlobUrls = new Set()
  const create = URL.createObjectURL.bind(URL), revoke = URL.revokeObjectURL.bind(URL)
  URL.createObjectURL = value => { const url = create(value); window.s03ActiveBlobUrls.add(url); return url }
  URL.revokeObjectURL = url => { window.s03ActiveBlobUrls.delete(url); revoke(url) }
})
await page.route('**/api/**', r => {
  const pathname = new URL(r.request().url()).pathname
  const json = pathname === '/api/auth/me' ? { id: 999, uid: 's03-browser-user', username: 'S03浏览器验证', role: 'user' } : pathname === '/api/system/info' ? { success: true, data: { organization: { name: '元垒', avatar: '/favicon.svg', logo: '/favicon.svg' }, branding: { name: '元垒' } } } : pathname === '/api/agents' ? { agents: [] } : []
  return r.fulfill({ json })
})
const check = (condition, message) => { assert.ok(condition, message); checks.push(message) }
const ready = async () => { await page.waitForFunction(() => document.querySelector('.theme-host') && !document.querySelector('.preview-state') && !document.querySelector('.theme-block[data-state="loading"]'), { timeout: 10000 }) }
const tools = async () => { if (!(await page.locator('.preview-tools').evaluate(el => el.open))) await page.locator('.preview-tools summary').click() }
const theme = async value => { await page.getByLabel('选择主题', { exact: true }).selectOption(value); await ready() }
const navigate = async name => {
  const toggle = page.locator('.theme-mobile-menu')
  if (await toggle.isVisible() && await toggle.getAttribute('aria-expanded') !== 'true') await toggle.click()
  await page.locator('.theme-page-navigation').getByRole('button', { name, exact: true }).click()
  await ready()
}
const open = async (type, id) => { await page.locator(`[data-object-key="${type}:${id}"]`).first().click(); await page.waitForSelector('.theme-detail') }
const back = async () => { await page.locator('[data-return]').click(); await ready() }
try {
  await page.goto(base + '/projects/theme-preview')
  await ready()
  check((await page.locator('.preview-banner').innerText()).includes('均为合成数据'), '模拟范围持续可见')
  check(await page.getByRole('link', { name: '返回主题管理' }).count() === 1, '真实平台返回入口存在')
  for (const [id, names] of [['sample-default', ['Dashboard', '工作台', '议题列表']], ['sample-research', ['课题脉络', '证据资料', '研究结论']]]) {
    await theme(id)
    for (const name of names) {
      await navigate(name)
      check(await page.locator('.theme-intro h1').innerText() === name, `${name}加载正确`)
      if (name === '证据资料') {
        check(await page.locator('.theme-image img').evaluate(img => img.complete && img.naturalWidth > 0), 'PNG Blob实际解码')
        check((await page.locator('[data-block="survey"]').innerText()).includes('24'), '指定JSON按内容展示')
        await page.locator('.theme-image img').evaluate(img => { img.src = 'data:image/png;base64,iVBORw0KGgoAAAAA' })
        await page.getByText('PNG 图像无法解码，请核对资料内容。', { exact: true }).waitFor()
        check(await page.getByRole('button', { name: '重新读取图像' }).count() === 1, '真实PNG解码失败明确可恢复')
        await page.getByRole('button', { name: '重新读取图像' }).click(); await ready()
        await page.waitForFunction(() => document.querySelector('.theme-image img')?.naturalWidth > 0)
      }
      await page.screenshot({ path: path.join(out, `${id}-${name}-light-1440.png`), fullPage: true })
    }
  }
  await theme('sample-default'); await navigate('Dashboard')
  await open('workTask', 'preview-market-work-interviews')
  check((await page.locator('.theme-detail').innerText()).includes('任务来源版本 1 · 当前决定版本 2'), '冻结来源版本与当前版本区分')
  await back()
  await theme('sample-research'); await navigate('研究结论')
  await open('workTask', 'preview-market-work-interviews')
  check((await page.locator('.theme-detail').innerText()).includes('workTask:preview-market-work-interviews'), '两主题任务身份一致')
  await back()
  check((await page.locator('[data-block="conclusions"]').innerText()).includes('无来源议题'), '无来源议题决定合法展示')
  await open('decision', 'preview-market-decision-pilot')
  check((await page.locator('.theme-detail').innerText()).includes('decision:preview-market-decision-pilot'), '决定入口准确')
  await page.locator('.theme-detail').getByRole('button', { name: '是否进入区域 A 市场', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.theme-detail')?.textContent.includes('topic:preview-market-topic-entry'))
  await back()
  check(await page.locator('.theme-intro h1').innerText() === '研究结论', '多层钻取返回最初来源页')
  await theme('sample-default'); await navigate('议题列表')
  await page.getByLabel('搜索议题标题').fill('试点定价')
  await page.getByLabel('筛选议题进展').selectOption('open'); await ready()
  await open('topic', 'preview-market-topic-pricing'); await back()
  check(await page.getByLabel('搜索议题标题').inputValue() === '试点定价' && await page.getByLabel('筛选议题进展').inputValue() === 'open', '返回保留搜索与筛选')
  check(await page.evaluate(() => document.activeElement?.dataset.objectKey === 'topic:preview-market-topic-pricing'), '返回恢复来源对象焦点')
  await navigate('工作台'); await page.locator('[data-select="preview-market-topic-pricing"]').click(); await ready()
  await theme('sample-research')
  check(await page.locator('[data-select="preview-market-topic-pricing"]').getAttribute('aria-pressed') === 'true', '切主题保留同一议题选择')
  await open('topic', 'preview-market-topic-pricing'); await back()
  check(await page.locator('[data-select="preview-market-topic-pricing"]').getAttribute('aria-pressed') === 'true', '返回保留主从选择')
  await navigate('证据资料'); await tools()
  for (const [value, text] of [['missing', '指定项目文件不存在'], ['unbound', '指定项目文件尚未绑定'], ['error', '合成读取失败'], ['denied', '合成权限拒绝']]) {
    await page.getByLabel('合成响应状态').selectOption(value); await ready()
    check((await page.locator('[data-block="survey"]').innerText()).includes(text), `${value}文件状态准确`)
    check(await page.locator('[data-block="survey"] .theme-file-metrics').count() === 0, `${value}清空旧资料`)
  }
  await page.screenshot({ path: path.join(out, 'resource-denied-light-1440.png'), fullPage: true })
  await page.getByLabel('合成响应状态').selectOption('empty'); await ready(); await navigate('课题脉络')
  check(await page.locator('.theme-block[data-state="empty"]').count() > 0, '空业务与加载、错误区分')
  await page.getByLabel('合成响应状态').selectOption('ready'); await ready()
  for (const value of ['unknown', 'binding', 'version']) {
    await page.getByLabel('主题定义验例').selectOption(value)
    await page.getByRole('heading', { name: '主题加载失败' }).waitFor()
    check(await page.locator('.theme-host:visible').count() === 0, `${value}整份定义拒绝`)
    check(await page.getByLabel('选择主题', { exact: true }).inputValue() === 'sample-research', `${value}不静默改为默认主题`)
  }
  await page.screenshot({ path: path.join(out, 'invalid-definition-light-1440.png'), fullPage: true })
  await page.getByLabel('主题定义验例').selectOption('valid'); await ready()
  await page.getByLabel('合成数据延迟').selectOption('1200')
  await page.waitForSelector('.theme-block[data-state="loading"]')
  check((await page.locator('.theme-block[data-state="loading"]').first().innerText()).includes('正在读取'), '加载状态可观察')
  await page.getByLabel('选择合成项目').selectOption('preview-service'); await ready(); await page.waitForTimeout(1400)
  check(!(await page.locator('.theme-content').innerText()).includes('是否进入区域 A 市场'), '迟到项目DTO不污染新项目')
  await page.locator('[data-select="preview-service-topic-pricing"]').click()
  await page.locator('[data-select="preview-service-topic-entry"]').click()
  await ready(); await page.waitForTimeout(1400)
  check((await page.locator('[data-block="question"]').innerText()).includes('是否增加异步服务支持'), '迟到选择DTO不污染当前议题')
  await page.getByLabel('合成响应状态').selectOption('error')
  await page.getByLabel('合成响应状态').selectOption('ready')
  await theme('sample-default'); await page.waitForTimeout(1400)
  check(await page.locator('.theme-intro h1').innerText() === 'Dashboard' && await page.locator('.theme-block[data-state="error"]').count() === 0, '旧主题数据与旧错误不提交')
  await page.getByLabel('合成数据延迟').selectOption('0'); await ready()
  await theme('sample-research'); await navigate('证据资料')
  check(await page.locator('[data-block="survey"] .theme-file-metrics > div').filter({ has: page.getByText('访谈样本', { exact: true }) }).locator('strong').innerText() === '12', '服务项目JSON展示自身12份资料')
  check((await page.locator('[data-block="distribution"]').innerText()).includes('固定包内图像') && (await page.locator('.theme-image img').getAttribute('alt')).includes('不随项目变化'), '固定图像明确为独立示例，不冒充项目资料派生图')
  await theme('sample-default')
  await page.getByLabel('选择合成项目').selectOption('preview-market'); await ready()
  if (await page.locator('.preview-tools').evaluate(el => el.open)) await page.locator('.preview-tools summary').click()
  await page.getByRole('button', { name: '切换明暗样式' }).click()
  await page.screenshot({ path: path.join(out, 'default-dashboard-dark-1440.png'), fullPage: true })
  for (const width of [1024, 768, 390, 375]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const [id, names] of [['sample-default', ['Dashboard', '工作台', '议题列表']], ['sample-research', ['课题脉络', '证据资料', '研究结论']]]) {
      await theme(id)
      for (const name of names) {
        await navigate(name)
        check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px ${name}无整页横溢出`)
      }
    }
    if (width === 390) await page.screenshot({ path: path.join(out, 'research-conclusions-dark-390.png'), fullPage: true })
  }
  await page.getByRole('button', { name: '切换明暗样式' }).click(); await navigate('课题脉络')
  await page.locator('[data-select="preview-market-topic-channel"]').focus(); await page.keyboard.press('Enter'); await ready()
  check(await page.locator('[data-select="preview-market-topic-channel"]').getAttribute('aria-pressed') === 'true', '键盘Enter选择长标题议题')
  await page.keyboard.press('Tab'); check(await page.evaluate(() => document.activeElement !== document.body), '键盘焦点可达')
  await page.locator('.theme-content').evaluate(el => { el.scrollTop = 0 }); await page.locator('.theme-intro h1').focus()
  await page.screenshot({ path: path.join(out, 'research-context-light-375.png'), fullPage: true })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.getByRole('link', { name: '返回主题管理' }).click(); await page.waitForURL(/\/projects\?tab=themes/)
  check(await page.evaluate(() => window.s03ActiveBlobUrls.size === 0), '离开宿主回收全部图片Blob URL')
  await page.getByRole('link', { name: '预览两套主题（合成数据）' }).click(); await ready()
  check(page.url().endsWith('/projects/theme-preview'), '预览入口从真实主题管理可发现并准确返回')
  check(writes.length === 0, '无平台业务写请求')
  check(errors.length === 0, `无浏览器脚本错误：${errors.join('；')}`)
  assert.deepEqual(await hashes(), sourceHashes, '浏览器验证期间源码不可变化')
  await writeFile(path.join(out, 'browser-receipt.json'), JSON.stringify({ result: 'Passed', checks, errors, writes, platformReadPaths: [...new Set(urls)], sourceHashes, limitations: ['认证和平台列表为本浏览器拦截响应，不证明真实授权', '业务／文件／详情来自明确合成适配，未接真实后端', '截图用于审美判断，DOM断言证明交互'] }, null, 2) + '\n')
  console.log(JSON.stringify({ result: 'Passed', checks: checks.length, writes: writes.length, errors }))
} finally { await browser.close() }
