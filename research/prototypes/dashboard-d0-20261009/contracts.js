// 合成稿有限结构检查；未实现生产授权、数据或发布验证。
export function inspectDefinition(definition, bindings, materials) {
  const errors = []
  const add = (pointer, code) => errors.push({ pointer, code })
  if (definition.schema_version !== 1) add('/definition/schema_version', 'unsupported_schema')
  for (const [id, binding] of Object.entries(bindings)) {
    if ('project_id' in binding) add(`/bindings/${id}/project_id`, 'scope_override_forbidden')
  }
  function visit(node, pointer) {
    if (node.component && !materials.includes(node.component)) add(`${pointer}/component`, 'unknown_component')
    if (node.action) {
      if (!['open-result', 'open-work', 'open-topic', 'open-decision'].includes(node.action.type)) add(`${pointer}/action/type`, 'write_action_forbidden')
      if ('url' in node.action) add(`${pointer}/action/url`, 'unknown_field')
    }
    if (node.mapping?.value === 'untyped_money') add(`${pointer}/mapping/value`, 'unknown_field_mapping')
    node.children?.forEach((child, index) => visit(child, `${pointer}/children/${index}`))
  }
  visit(definition.layout, '/definition/layout')
  return errors
}
