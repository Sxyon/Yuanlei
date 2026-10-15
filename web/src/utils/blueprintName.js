/** 新建时自动补全受控 Markdown 后缀，保留服务端文件名约束。 */
export function normalizeBlueprintName(input) {
  const raw = String(input || '').trim()
  const name = raw.toLowerCase().endsWith('.md') ? `${raw.slice(0, -3)}.md` : `${raw}.md`
  const stem = name.slice(0, -3)
  if (
    Array.from(name).length > 120 ||
    new TextEncoder().encode(stem).length > 194 ||
    !/^[\p{L}\p{N}][\p{L}\p{N}._，。！？、；：（）【】《》“”‘’！!#$%&'+,;=@^`~(){}[\]+-]*\.md$/u.test(
      name
    )
  )
    return null
  return name
}

/** 在界面中只展示蓝图名称，文件后缀留给存储协议。 */
export const displayBlueprintName = (name) => String(name || '').replace(/\.md$/, '')

/** 首行Markdown标题作为文档标题，缺省时沿用文件显示名。 */
export function blueprintDocumentHeading(name, content) {
  return String(content || '').match(/^\s*# +([^\n]+)(?:\n|$)/)?.[1].trim() || displayBlueprintName(name)
}

/** 标题由文档抬头呈现，阅读正文保留其余原文，编辑仍读取完整文件。 */
export const blueprintDocumentBody = content => String(content || '').replace(/^\s*# +[^\n]+(?:\n|$)/, '')
