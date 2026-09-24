import test from 'node:test'
import assert from 'node:assert/strict'

import { DASHBOARD_CSP, createDashboardSrcdoc } from '../../src/utils/dashboardFrame.js'

test('static dashboard frame injects a strict no-script, no-network CSP', () => {
  assert.equal(DASHBOARD_CSP.includes('script-src'), false)
  assert.ok(DASHBOARD_CSP.includes("default-src 'none'"))
  assert.ok(DASHBOARD_CSP.includes("connect-src 'none'"))

  const untrusted = '<!-- <head> --><html><head><title>t</title></head><body><img src="https://example.com/pixel"></body></html>'
  const srcdoc = createDashboardSrcdoc(untrusted)
  const expectedHead = `<!doctype html><html lang="zh-CN"><head><meta http-equiv="Content-Security-Policy" content="${DASHBOARD_CSP}"></head><body>`
  assert.ok(srcdoc.startsWith(expectedHead))
  assert.ok(srcdoc.indexOf('Content-Security-Policy') < srcdoc.indexOf(untrusted))
  assert.ok(srcdoc.includes(untrusted))
})
