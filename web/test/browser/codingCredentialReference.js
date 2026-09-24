// 已登录开发环境：playwright-cli -s=<session> run-code --filename=web/test/browser/codingCredentialReference.js
// 创建一次性模型供应商 fixture，验证编码凭据卡三模式与引用自检，结束后清理。
// prettier-ignore
async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  const token = await page.evaluate(() => window.localStorage.getItem('user_token'))
  if (!token) throw new Error('需要已登录会话：缺少 user_token')
  const headers = { Authorization: `Bearer ${token}` }
  const suffix = Math.random().toString(16).slice(2, 10)
  const providerId = `pytest-ui-coding-ref-${suffix}`
  const providerName = `UI验证供应商-${suffix}`
  const consoleErrors = []
  const failedRequests = []

  const created = await page.request.post('/api/system/model-providers', {
    headers,
    data: {
      provider_id: providerId,
      display_name: providerName,
      provider_type: 'openai',
      default_protocol: 'openai_compatible',
      base_url: 'https://api.ui-pytest.example.com/v1',
      api_key: 'sk-ui-provider-secret',
      capabilities: ['chat'],
      enabled_models: [{ id: 'ui-chat-model', type: 'chat' }],
      is_enabled: true
    }
  })
  check(created.ok(), `创建供应商失败: ${created.status()} ${await created.text()}`)

  try {
    page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()) })
    page.on('requestfailed', (req) => failedRequests.push(`${req.method()} ${req.url()}`))

    await page.goto('http://localhost:5173/agent-manage?tab=agents', { waitUntil: 'networkidle' })
    await page.locator('.user-info-component').click()
    await page.locator('.ant-dropdown-menu-item', { hasText: '设置' }).first().click()
    await page.locator('.sider-item', { hasText: '编码凭据' }).first().click()
    const card = page.locator('.coding-credential-settings')
    await card.waitFor()

    await page.locator('label.ant-radio-button-wrapper', { hasText: '引用·共用密钥' }).click()
    await card.locator('.ant-form-item', { hasText: '模型供应商' }).locator('.ant-select').click()
    await page.locator('.ant-select-item-option', { hasText: providerName }).first().click()
    await card.locator('.ant-form-item').filter({ has: page.locator('label', { hasText: /^模型$/ }) }).locator('.ant-select').click()
    await page.locator('.ant-select-item-option', { hasText: 'ui-chat-model' }).first().click()
    check(await card.locator('.ant-form-item', { hasText: 'API Key' }).count() === 0, '共用密钥模式不应要求 API Key')

    await page.getByRole('button', { name: '保存凭据' }).click()
    await page.locator('.credential-item', { hasText: 'ui-chat-model' }).waitFor()
    const savedText = await page.locator('.credential-item', { hasText: 'ui-chat-model' }).first().innerText()
    check(savedText.includes('共用密钥'), '列表未回显共用密钥模式')
    check(savedText.includes('可用'), '列表未自检为可用')

    const disabled = await page.request.put(`/api/system/model-providers/${providerId}`, { headers, data: { is_enabled: false } })
    check(disabled.ok(), `停用供应商失败: ${disabled.status()}`)
    await page.locator('.refresh-btn').last().click()
    await page.waitForTimeout(800)
    const item = page.locator('.credential-item', { hasText: 'ui-chat-model' }).first()
    await item.waitFor()
    check((await item.innerText()).includes('供应商已停用'), '供应商停用后未标记不可用')
    check(consoleErrors.length === 0, `页面 console error: ${consoleErrors[0]}`)
    check(failedRequests.length === 0, `请求失败: ${failedRequests[0]}`)

    return { mode: 'inherit', selfCheck: 'unavailable-after-disable' }
  } finally {
    await page.request.delete('/api/user/coding-credentials', { headers, params: { executor: 'opencode', provider: providerId } })
    await page.request.delete(`/api/system/model-providers/${providerId}`, { headers })
  }
}
