// 已登录开发环境：playwright-cli -s=<session> run-code --filename=web/test/browser/projectDashboardStaticFrame.js
// 文件内容由 CLI 作为函数表达式执行，不添加前导分号
async (page) => {
  const check = (condition, message) => {
    if (!condition) throw new Error(message)
  }

  const token = await page.evaluate(() => window.localStorage.getItem('user_token'))
  check(Boolean(token), '需要已登录会话：缺少 user_token')

  const projectId = `browser-dashboard-${Math.random().toString(16).slice(2, 10)}`
  const externalRequests = []
  const scriptHtml = `<!-- <head> --><!doctype html><html><head><style>body { background: url('https://example.com/pixel') }</style></head><body><img src="https://example.com/steal"><script>document.body.dataset.ran = 'yes'; fetch('https://example.com/steal')</script></body></html>`
  const readyPayload = {
    state: 'ready', revision: 3, sha256: 'a'.repeat(64), size: scriptHtml.length,
    updated_at: '2026-09-22T00:00:00', html: scriptHtml
  }

  page.on('request', (request) => {
    if (request.url().includes('example.com')) externalRequests.push(request.url())
  })
  await page.route('**/api/projects/*/dashboard', (route) => route.fulfill({ json: readyPayload }))

  try {
    await page.goto(`http://localhost:5173/projects/${projectId}/dashboard`, { waitUntil: 'networkidle' })
    const frameElement = await page.waitForSelector('iframe.dashboard-frame', { timeout: 10000 })
    check(await frameElement.getAttribute('sandbox') === '', 'Dashboard iframe 必须使用空 sandbox')

    const frame = page.frames().find((item) => item !== page.mainFrame() && item.url() === 'about:srcdoc')
    check(Boolean(frame), '未找到 Dashboard iframe')
    await page.waitForTimeout(300)
    check((await frame.content()).includes('Content-Security-Policy'), 'Dashboard 文档必须含有效 CSP')
    check(await frame.evaluate(() => document.body.dataset.ran) !== 'yes', 'Dashboard 脚本不得执行')
    check(externalRequests.length === 0, `iframe 不应发出外网请求：${externalRequests.join(', ')}`)

    await page.getByRole('button', { name: '在项目对话中编辑' }).click()
    await page.waitForURL(/\/agent\?project_id=/, { timeout: 10000 })

    await page.screenshot({ path: '/tmp/project-dashboard-static.png', fullPage: true })
    return { ok: true, projectId }
  } finally {
    await page.unroute('**/api/projects/*/dashboard').catch(() => {})
  }
}
