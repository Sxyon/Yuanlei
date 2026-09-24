// 已登录开发环境：playwright-cli -s=<session> run-code --filename=web/test/browser/agentExecutionConfig.js
// 创建一次性项目/智能体 fixture 验证「沙盒与编码」配置面，结束后按 slug 清理。
// prettier-ignore
async (page) => {
  const check = (condition, message) => { if (!condition) throw new Error(message) }
  const token = await page.evaluate(() => window.localStorage.getItem('user_token'))
  if (!token) throw new Error('需要已登录会话：缺少 user_token')
  const headers = { Authorization: `Bearer ${token}` }
  const suffix = Math.random().toString(16).slice(2, 10)
  const projectDir = `pytest-ui-execution-${suffix}`
  const projectName = `UI验证-${suffix}`
  const agentName = `UI验证Agent-${suffix}`
  const projectAgentName = `UI验证项目员工-${suffix}`
  const created = []

  const create = async (url, data) => {
    const response = await page.request.post(url, { headers, data })
    check(response.ok(), `创建 fixture 失败: ${url} ${response.status()} ${await response.text()}`)
    return response.json()
  }

  let projectId = null
  try {
    await create('/api/workspace/directory', { parent_path: '/', name: projectDir })
    projectId = (await create('/api/projects', {
      request_id: `pytest-ui-execution-${suffix}`,
      name: projectName,
      workdir: { mode: 'linked', path: projectDir }
    })).id

    const agent = await create('/api/agent', {
      name: agentName,
      backend_id: 'ChatbotAgent',
      config_json: {
        sandbox: { mode: 'dedicated', lifecycle: 'persistent', idle_suspend_seconds: 900 },
        coding: { executors: ['opencode'], default_executor: 'opencode' }
      }
    })
    created.push(agent.agent.slug)
    const projectAgent = await create(`/api/projects/${projectId}/agents`, {
      name: projectAgentName,
      backend_id: 'ChatbotAgent',
      config_json: {
        context: { system_prompt: 'UI 验证' },
        sandbox: { mode: 'dedicated', lifecycle: 'persistent' },
        coding: { executors: ['opencode', 'codex'], default_executor: 'opencode' }
      }
    })
    created.push(projectAgent.slug)

    const consoleErrors = []
    page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()) })

    // Agent 级：回显专属沙盒与执行器
    await page.goto('http://localhost:5173/agent-manage?tab=agents', { waitUntil: 'networkidle' })
    await page.locator('.agent-card').filter({ hasText: agentName }).first.click()
    const agentTab = page.locator('.agent-modal-nav-item', { hasText: '沙盒与编码' })
    await agentTab.waitFor()
    await agentTab.click()
    const form = page.locator('.agent-execution-form')
    await form.waitFor()
    check((await form.innerText()).includes('沙盒生命周期'), 'Agent 弹窗缺少沙盒生命周期区块')
    check(await page.locator('label.ant-radio-button-wrapper-checked', { hasText: '专属' }).count() === 1, 'Agent 弹窗未回显专属模式')
    check(await page.locator('.ant-checkbox-wrapper-checked', { hasText: 'OpenCode' }).count() === 1, 'Agent 弹窗未回显 OpenCode')
    await page.keyboard.press('Escape')
    await form.waitFor({ state: 'hidden' })

    // 项目覆盖：继承值、恢复继承入口、预热按钮、context 区回归
    await page.goto('http://localhost:5173/agent-manage?tab=projects', { waitUntil: 'networkidle' })
    await page.locator('.ant-select').first().click()
    await page.locator('.ant-select-item-option', { hasText: projectName }).first().click()
    const card = page.locator('.agent-card').filter({ hasText: projectAgentName }).first
    await card.waitFor()
    await card.hover()
    await card.locator('button').last().click()
    await page.locator('.ant-dropdown-menu-item', { hasText: '编辑项目配置' }).click()
    const sectionTab = page.locator('.agent-modal-nav-item', { hasText: '沙盒与编码' })
    await sectionTab.waitFor()
    await sectionTab.click()
    const overrideForm = page.locator('.agent-execution-form')
    await overrideForm.waitFor()
    check((await overrideForm.innerText()).includes('恢复继承'), '项目覆盖缺少恢复继承入口')
    check(await page.locator('label.ant-radio-button-wrapper-checked', { hasText: '专属' }).count() === 1, '项目覆盖未回显继承的专属模式')
    const warm = page.getByRole('button', { name: '立即预热' })
    check(await warm.count() === 1 && await warm.isEnabled(), '项目覆盖缺少可用的预热入口')
    await page.locator('.agent-modal-nav-item', { hasText: '模型配置' }).click()
    check(await page.locator('.project-agent-config-form').isVisible(), '项目覆盖 context 配置区回归')
    check(consoleErrors.length === 0, `页面出现 console error: ${consoleErrors[0]}`)

    return { agentExecution: 'ok', projectExecution: 'ok', consoleErrors: 0 }
  } finally {
    for (const slug of created) await page.request.delete(`/api/agent/${slug}`, { headers })
    if (projectId) await page.request.delete(`/api/projects/${projectId}`, { headers })
    await page.request.delete('/api/workspace/file', { headers, params: { path: projectDir } })
  }
}
