import { validateDefinition } from '../definition.mjs'

/** 只把已校验主题转成内部Schema，原始值不进入表达式或组件解析。 */
export function compilePage(theme, pageId, system, resources, openObject) {
  validateDefinition(theme)
  const page = theme.pages.find(page => page.id === pageId)
  if (!page) throw Error('page_not_declared')
  return page.blocks.map(block => ({
    $cmp: 'ThemeBlock',
    props: { __raw__block: block, __raw__system: system, __raw__resources: resources, __raw__openObject: openObject }
  }))
}
