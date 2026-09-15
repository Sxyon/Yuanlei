import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const readSource = (relativePath) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

test('共享下拉样式由全局样式表拥有', () => {
  const globalStyles = readSource('../../src/assets/css/main.css')
  const agentView = readSource('../../src/views/AgentView.vue')
  const approvalSelector = readSource('../../src/components/ToolApprovalModeSelector.vue')

  const actionDropdown = readSource('../../src/components/common/ActionDropdown.vue')
  assert.match(approvalSelector, /<ActionDropdown/)
  assert.match(agentView, /<ActionDropdown/)
  assert.match(actionDropdown, /overlay-class-name="config-dropdown-overlay"/)
  assert.match(globalStyles, /\.config-dropdown-overlay \.config-dropdown-panel/)
  assert.match(globalStyles, /\.config-dropdown-overlay \.config-dropdown-item/)
  assert.doesNotMatch(agentView, /\.config-dropdown-overlay \.config-dropdown-panel/)
})
