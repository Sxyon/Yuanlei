export const systemBindings = ['project', 'topics', 'discussions', 'decisions', 'tasks']
export const fileBindings = ['metrics', 'image', 'report', 'notes']
export const blockTypes = ['summary', 'records', 'json', 'image', 'html', 'markdown']

/** 将实验定义限制在有限组件和逻辑数据名内。 */
export function validateDefinition(value) {
  const keys = (object, allowed) => {
    if (!object || typeof object !== 'object' || Array.isArray(object) || Object.keys(object).some(key => !allowed.includes(key))) throw Error('unknown_field')
  }
  const text = value => typeof value === 'string' && value.length > 0 && value.length <= 120
  keys(value, ['id', 'version', 'name', 'topicLabel', 'layout', 'pages'])
  if (!text(value.id) || !text(value.version) || !text(value.name) || !text(value.topicLabel) || !['grid', 'reading'].includes(value.layout)) throw Error('invalid_metadata')
  if (!Array.isArray(value.pages) || value.pages.length < 1 || value.pages.length > 8) throw Error('invalid_pages')
  const ids = new Set()
  for (const page of value.pages) {
    keys(page, ['id', 'title', 'blocks'])
    if (!text(page.id) || !text(page.title) || ids.has(page.id)) throw Error('invalid_page')
    ids.add(page.id)
    if (!Array.isArray(page.blocks) || page.blocks.length > 12) throw Error('invalid_blocks')
    for (const block of page.blocks) {
      keys(block, ['type', 'binding', 'title'])
      if (!blockTypes.includes(block.type)) throw Error('unknown_component')
      const allowed = ['summary', 'records'].includes(block.type) ? systemBindings : fileBindings
      if (!allowed.includes(block.binding)) throw Error('binding_not_declared')
      const format = { json: 'metrics', image: 'image', html: 'report', markdown: 'notes', summary: 'project' }
      if ((block.type === 'records' && block.binding === 'project') || (format[block.type] && format[block.type] !== block.binding) || !text(block.title)) throw Error('invalid_block')
    }
  }
  return value
}
