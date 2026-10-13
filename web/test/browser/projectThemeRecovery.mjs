/* global process */
import assert from 'node:assert/strict'
import { readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fixture = JSON.parse(await readFile(process.env.THEME_EVIDENCE_SESSION, 'utf8'))
const out = path.resolve(process.env.THEME_EVIDENCE_OUTPUT)
const expected = JSON.parse(await readFile(path.join(out, 'browser-receipt.json'), 'utf8')).selected
const api = process.env.THEME_RECOVERY_API || 'http://127.0.0.1:15061'
const web = process.env.THEME_EVIDENCE_WEB || 'http://localhost:5173'
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const requests = [], errors = []
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(token => localStorage.setItem('user_token', token), fixture.users[0].token)
// 恢复副本只读；传递实际HTTP响应，不合成账号、版本或资源。
await page.route('**/api/**', async route => {
  const request = route.request(), url = new URL(request.url())
  assert.equal(request.method(), 'GET', '恢复浏览器不写数据库或选择')
  const response = await page.request.fetch(api + url.pathname + url.search, { headers: request.headers() })
  requests.push({ path: url.pathname, status: response.status() })
  await route.fulfill({ response })
})
try {
  await page.goto(`${web}/projects/${expected.projectId}/dashboard?view=theme`)
  await page.locator('.project-theme-panel .theme-host').waitFor()
  const headers = { Authorization: `Bearer ${fixture.users[0].token}` }
  const loaded = await (await page.request.get(`${api}/api/projects/${expected.projectId}/theme`, { headers })).json()
  assert.equal(loaded.binding.version_id, expected.versionId)
  assert.equal(loaded.generation, expected.generation)
  assert.equal(loaded.package.digest, expected.digest)
  assert.ok((await page.locator('.theme-status').innerText()).includes(loaded.version.version))
  await page.screenshot({ path: path.join(out, 'restored-selection-light-1440.png'), fullPage: true })
  await page.goto(`${web}/projects/${fixture.projects[1].id}/dashboard?view=theme`)
  await page.locator('.project-theme-panel .theme-host').waitFor()
  await page.getByRole('button', { name: '证据资料', exact: true }).click()
  await page.locator('.theme-host img').waitFor()
  assert.ok(await page.locator('.theme-host img').evaluate(img => img.complete && img.naturalWidth > 0))
  assert.ok((await page.locator('.theme-host').innerText()).includes('项目文件内容待 S05 接通'))
  await page.setViewportSize({ width: 375, height: 1000 })
  await page.locator('.theme-host img').scrollIntoViewIfNeeded()
  await page.screenshot({ path: path.join(out, 'restored-resource-light-375.png'), fullPage: true })
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
  assert.equal(errors.length, 0)
  assert.ok(requests.every(request => request.status < 400))
  await writeFile(path.join(out, 'recovery-browser-receipt.json'), JSON.stringify({ restoredSelection: expected, exactVersionAndDigest: true, pngDecoded: true, fileContentsPendingS05: true, responsive375: true, scriptErrors: errors, requests }, null, 2) + '\n')
  console.log(JSON.stringify({ exactVersionAndDigest: true, pngDecoded: true, requests: requests.length, scriptErrors: errors.length }))
} finally { await browser.close() }
