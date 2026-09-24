/** 第一版项目 Dashboard 的静态、无网络 iframe 封装。 */

export const DASHBOARD_CSP = [
  "default-src 'none'",
  "style-src 'unsafe-inline'",
  'img-src data:',
  'font-src data:',
  "connect-src 'none'",
  "media-src 'none'",
  "object-src 'none'",
  "frame-src 'none'",
  "form-action 'none'",
  "base-uri 'none'"
].join('; ')

export function createDashboardSrcdoc(html) {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${DASHBOARD_CSP}">`
  const content = typeof html === 'string' ? html : ''
  // 页面内容不拥有文档壳；这样注释或畸形 HTML 里的伪造 <head> 不能把 CSP
  // 插进非活动节点。后端已拒绝 script、meta 与页面导航，CSP 是第二道边界。
  return `<!doctype html><html lang="zh-CN"><head>${meta}</head><body><div data-dashboard-content>${content}</div></body></html>`
}
