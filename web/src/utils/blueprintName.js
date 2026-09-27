/** 新建时自动补全受控 Markdown 后缀，保留服务端文件名约束。 */
export function normalizeBlueprintName(input) {
  const raw = String(input || '').trim()
  const name = raw.endsWith('.md') ? raw : `${raw}.md`
  if (name.length > 120 || !/^[a-z0-9][a-z0-9._-]*\.md$/.test(name)) return null
  return name
}

/** 在界面中只展示蓝图名称，文件后缀留给存储协议。 */
export const displayBlueprintName = (name) => String(name || '').replace(/\.md$/, '')
