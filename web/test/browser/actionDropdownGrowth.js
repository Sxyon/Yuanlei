// 使用已登录开发环境：playwright-cli -s=<session> run-code --filename=web/test/browser/actionDropdownGrowth.js
// 文件内容由 CLI 作为函数表达式执行，不添加前导分号。
// prettier-ignore
async (page) => {
  await page.unrouteAll({ behavior: 'ignoreErrors' })
  await page.goto('http://localhost:5173/agent')
  await page.setViewportSize({ width: 1440, height: 900 })
  let release
  const gate = new Promise((resolve) => (release = resolve))
  await page.route('**/api/system/model-providers/models/v2?*', async (route) => {
    await gate
    await route.fulfill({
      json: {
        success: true,
        data: {
          fixture: {
            models: Array.from({ length: 40 }, (_, i) => ({
              spec: `fixture:${i}`,
              display_name: `测试模型 ${i + 1}`
            }))
          }
        }
      }
    })
  })
  const trigger = page.locator('.input-model-selector button.config-dropdown-trigger')
  await trigger.click()
  const panel = page.locator('.action-dropdown-panel:visible')
  await panel.getByRole('status').filter({ hasText: '正在加载模型' }).waitFor()
  await page.waitForTimeout(350)
  await page.evaluate(() => {
    window.__growthFrames = []
    window.__growthSampling = true
    const sample = () => {
      const p = [...document.querySelectorAll('.action-dropdown-panel')].find(
        (el) => el.getBoundingClientRect().height
      )
      const t = document.querySelector('.input-model-selector button.config-dropdown-trigger')
      if (p && t) {
        const r = p.getBoundingClientRect()
        window.__growthFrames.push({
          height: r.height,
          bottom: r.bottom,
          drift: r.bottom - (t.getBoundingClientRect().top - 4)
        })
      }
      if (window.__growthSampling) requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
  release()
  await panel.locator('.model-option').nth(39).waitFor({ state: 'attached' })
  await page.waitForTimeout(700)
  const loadedHeight = await panel.evaluate((el) => el.getBoundingClientRect().height)
  await panel.getByRole('textbox', { name: '搜索模型' }).fill('测试模型 40')
  await page.waitForTimeout(500)
  const filteredCount = await panel.locator('.model-option').count()
  const filteredHeight = await panel.evaluate((el) => el.getBoundingClientRect().height)
  const result = await page.evaluate(() => {
    window.__growthSampling = false
    const frames = window.__growthFrames
    delete window.__growthFrames
    return {
      frames: frames.length,
      minHeight: Math.min(...frames.map((f) => f.height)),
      maxHeight: Math.max(...frames.map((f) => f.height)),
      maxBottomDrift: Math.max(...frames.map((f) => Math.abs(f.drift)))
    }
  })
  await page.unroute('**/api/system/model-providers/models/v2?*')
  await panel.press('Escape')
  Object.assign(result, { loadedHeight, filteredHeight, filteredCount })
  if (filteredCount !== 1 || loadedHeight - filteredHeight < 200) {
    throw new Error('筛选必须只留下一个选项，并让弹层明显缩短')
  }
  if (result.maxHeight - result.minHeight < 200) throw new Error('测试必须覆盖真实的大幅高度变化')
  if (result.maxBottomDrift > 1) throw new Error(`弹层底边偏离按钮 ${result.maxBottomDrift}px`)
  return result
}
