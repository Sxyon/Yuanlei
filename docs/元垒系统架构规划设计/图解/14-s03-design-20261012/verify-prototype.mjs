import assert from 'node:assert/strict'
import { mkdir, writeFile, readFile, unlink } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { createHash } from 'node:crypto'

// 只验证隔离设计原型；不得作为产品 ThemeHost 或真实后端接通的证据。
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const folder = path.dirname(fileURLToPath(import.meta.url))
const negative = process.argv.includes('--negative-control')
const source = path.join(folder, 'prototype.html')
const target = negative ? path.join(folder, `.negative-${process.pid}.html`) : source
if (negative) {
  const html = await readFile(source, 'utf8')
  assert.ok(html.includes('if(captured!==sequence)'), '负控必须移除真实generation拒绝')
  await writeFile(target, html.replace('if(captured!==sequence)', 'if(false)'))
}
const out = path.join(folder, 'browser')
await mkdir(out, { recursive: true })
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const failures = [], requests = [], checks = []
page.on('pageerror', e => failures.push(e.message))
page.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()) })
const check = (condition, message) => { assert.ok(condition, message); checks.push(message) }
const openTools = async () => { if (!(await page.locator('.prototype-controls').evaluate(el => el.open))) await page.locator('.prototype-controls summary').click() }
const selectTheme = async theme => page.locator('#theme').selectOption(theme)
const openPage = async id => {
  if ((await page.viewportSize()).width <= 768) {
    if (!(await page.locator('#nav').evaluate(el => el.classList.contains('open')))) await page.locator('#menu').click()
  }
  await page.locator(`#nav [data-page="${id}"]`).click()
}
try {
  await page.goto(pathToFileURL(target).href)
  check(await page.getByRole('heading', { name: 'Dashboard', exact: true }).count() === 1, '默认首页加载')
  for (const [theme, ids] of [['default', ['dashboard', 'workbench', 'topics']], ['research', ['context', 'evidence', 'conclusions']]]) {
    await selectTheme(theme)
    for (const id of ids) {
      await openPage(id)
      check(await page.locator('h1').count() === 1, `${id}唯一页标题`)
      if (id === 'evidence') check(await page.locator('img').evaluate(el => el.complete && el.naturalWidth > 0), 'PNG真实解码')
      await page.screenshot({ path: path.join(out, `${id}-light-1440.png`), fullPage: true })
    }
  }
  await selectTheme('default'); await openPage('dashboard')
  await page.locator('[data-id="topic-entry"]').scrollIntoViewIfNeeded()
  const sourceTop = await page.evaluate(() => scrollY)
  await page.locator('[data-id="topic-entry"]').click(); await page.locator('[data-back]').click()
  check(await page.evaluate(top => Math.abs(scrollY - top) <= 1, sourceTop), '返回恢复来源滚动')
  check(await page.evaluate(() => document.activeElement.dataset.id === 'topic-entry'), '返回恢复来源对象焦点')
  await openPage('topics')
  await page.locator('#filter').selectOption('open')
  await page.locator('#search').fill('试点定价'); await page.locator('#search').press('Tab')
  await page.locator('[data-id="topic-pricing"]').click()
  check((await page.locator('main').innerText()).includes('topic:topic-pricing'), '议题详情身份准确')
  await page.locator('[data-back]').click()
  check(await page.locator('#filter').inputValue() === 'open' && await page.locator('#search').inputValue() === '试点定价', '返回保留搜索与筛选')
  await openPage('workbench'); await page.locator('[data-select="topic-pricing"]').click()
  await page.locator('[data-id="work-cost"]').click()
  check((await page.locator('main').innerText()).includes('workTask:work-cost'), '正式任务准确入口')
  await page.locator('[data-id="topic-pricing"]').click(); await page.locator('[data-back]').click()
  check(await page.locator('[data-select="topic-pricing"]').getAttribute('aria-pressed') === 'true', '多层钻取返回原工作台及选择')
  await selectTheme('research'); await openPage('conclusions')
  await page.locator('[data-id="work-cost"]').click()
  check((await page.locator('main').innerText()).includes('workTask:work-cost'), '两主题正式任务身份一致')
  await page.locator('[data-back]').click(); await page.locator('[data-id="work-interviews"]').click()
  check((await page.locator('main').innerText()).includes('任务来源版本 1 · 当前决定版本 2'), '任务冻结来源与当前决定版本区分')
  await page.locator('[data-back]').click(); await page.locator('[data-id="decision-pilot"]').click()
  check((await page.locator('main').innerText()).includes('decision:decision-pilot'), '决定详情身份准确')
  await page.locator('[data-back]').click()
  check((await page.locator('#content').innerText()).includes('无来源议题 · 项目级决定'), '合法无来源议题决定可展示')
  await openPage('evidence')
  await openTools()
  for (const [scenario, expected] of [['missing', '指定资料文件缺失'], ['unbound', '尚未绑定指定资料'], ['error', '资料读取失败'], ['denied', '无权读取当前资料'], ['empty', '当前项目尚无业务记录'], ['loading', '正在读取合成页面']]) {
    await page.locator('#scenario').selectOption(scenario)
    check((await page.locator('#content').innerText()).includes(expected), `${scenario}可区分`)
  }
  await page.locator('#scenario').selectOption('ready')
  await openTools(); await page.locator('#delay').click()
  await page.locator('#project').selectOption('p2')
  await page.waitForTimeout(2200)
  check((await page.locator('#content').innerText()).includes('是否增加异步服务支持') && await page.locator('[data-delayed-payload]').count() === 0, '旧项目DTO未污染当前项目')
  await page.locator('[data-id="p2-topic-entry"]').click()
  check((await page.locator('main').innerText()).includes('p2-topic-entry'), '不同项目使用不同合成身份')
  await page.locator('[data-back]').click()
  await openTools(); await page.locator('#delay').click()
  await selectTheme('default'); await page.waitForTimeout(2200)
  check(await page.getByRole('heading', { name: 'Dashboard', exact: true }).count() === 1 && await page.locator('[data-delayed-payload]').count() === 0, '旧主题DTO未污染当前主题')
  await openPage('workbench')
  await openTools(); await page.locator('#delay').click()
  await page.locator('[data-select="p2-topic-pricing"]').click(); await page.waitForTimeout(2200)
  check(await page.locator('[data-select="p2-topic-pricing"]').getAttribute('aria-pressed') === 'true' && await page.locator('[data-delayed-payload]').count() === 0, '旧选择DTO未污染当前选择')
  await openTools(); await page.locator('#delay-error').click()
  await page.locator('#project').selectOption('p1'); await page.waitForTimeout(2200)
  check(await page.locator('[data-delayed-payload]').count() === 0 && !(await page.locator('#content').innerText()).includes('合成请求失败'), '旧项目错误不提交到当前页面')
  await openTools(); await page.locator('#delay').click(); await page.waitForTimeout(2200)
  check(await page.locator('[data-delayed-payload]').count() === 1, '同上下文合成DTO真实提交到内容区')
  await page.locator('[data-retry]').click()
  await page.locator('#project').selectOption('p1')
  await page.locator('#dark').click(); await page.screenshot({ path: path.join(out, 'dashboard-dark-1440.png'), fullPage: true })
  for (const width of [1024, 768, 390, 375]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const theme of ['default', 'research']) {
      await selectTheme(theme)
      for (const id of theme === 'default' ? ['dashboard', 'workbench', 'topics'] : ['context', 'evidence', 'conclusions']) {
        await openPage(id)
        check(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `${width}px ${id}无整页横溢出`)
      }
    }
    if (width === 390) await page.screenshot({ path: path.join(out, 'conclusions-dark-390.png'), fullPage: true })
  }
  await page.locator('#dark').click(); await openPage('context')
  await page.screenshot({ path: path.join(out, 'context-light-375.png'), fullPage: true })
  await page.locator('[data-select="topic-entry"]').focus(); await page.keyboard.press('ArrowDown')
  await page.keyboard.press('Tab')
  check(await page.evaluate(() => document.activeElement !== document.body), '键盘焦点可到达控件')
  await page.locator('[data-select="topic-pricing"]').focus(); await page.keyboard.press('Enter')
  check(await page.locator('[data-select="topic-pricing"]').getAttribute('aria-pressed') === 'true', '键盘Enter选择议题')
  check(failures.length === 0, `无浏览器脚本错误：${failures.join(',')}`)
  check(requests.length === 0, '原型不访问平台或外部HTTP接口')
  const digest = createHash('sha256').update(await readFile(path.join(folder, 'prototype.html'))).digest('hex')
  await writeFile(path.join(out, 'receipt.json'), JSON.stringify({ kind: 'isolated-design-prototype', result: 'Passed', prototypeSha256: digest, checks, failures, requests, limitations: ['不是产品ThemeHost或JSON包校验测试', '不是后端接通证据', '加载／错误由审阅工具触发', '不证明真实路由的来源返回'] }, null, 2) + '\n')
  console.log(JSON.stringify({ result: 'Passed', checks: checks.length, failures, externalRequests: requests.length }))
} finally { await browser.close(); if (negative) await unlink(target) }
