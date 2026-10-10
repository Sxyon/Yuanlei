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

// collaboration.read/1 的合成消费映射；真实权限与导航会话由宿主服务拥有。
export function collaborationObjectAction(projection, action, returnToken) {
  if (projection.projection_version !== 'collaboration.read/1') throw new Error('unsupported_projection')
  if (action.project_id !== projection.project_id || action.work_id !== projection.work_id) throw new Error('object_scope_mismatch')
  if (!returnToken || typeof returnToken !== 'string') throw new Error('return_token_required')
  const types = {
    'open-collaboration-question': 'collaboration-question',
    'open-collaboration-attempt': 'collaboration-attempt',
    'open-work-result': 'work-result',
  }
  const objectType = types[action.kind]
  if (!objectType) throw new Error('unsupported_collaboration_action')
  if (!projection.allowed_actions.some(candidate => JSON.stringify(candidate) === JSON.stringify(action))) throw new Error('action_not_in_projection')
  if (objectType === 'collaboration-question' && (!action.question_id || !action.question_revision || !action.node_id)) throw new Error('question_binding_missing')
  if (objectType === 'collaboration-attempt' && !action.attempt_id) throw new Error('attempt_binding_missing')
  if (objectType === 'work-result' && (!action.result_id || !action.attempt_id)) throw new Error('result_binding_missing')
  return { type: 'open-object', object_type: objectType, project_id: action.project_id, work_id: action.work_id,
    question_id: action.question_id, question_revision: action.question_revision, node_id: action.node_id,
    attempt_id: action.attempt_id, result_id: action.result_id, return_token: returnToken }
}

// 合成宿主registry查证准确对象；生产需当前认证主体和repository可见性查询。
export function resolveCollaborationObject(descriptor, objects, navigationSession) {
  if (descriptor.return_token !== navigationSession.token) throw new Error('return_token_invalid')
  const object = objects.find(item => item.project_id === descriptor.project_id && item.work_id === descriptor.work_id
    && item.object_type === descriptor.object_type
    && (item.question_id ?? null) === descriptor.question_id
    && (item.question_revision ?? null) === descriptor.question_revision
    && (item.node_id ?? null) === descriptor.node_id
    && (item.attempt_id ?? null) === descriptor.attempt_id
    && (item.result_id ?? null) === descriptor.result_id)
  if (!object) throw new Error('object_not_visible_or_stale')
  return { object_ref: object, return_token: navigationSession.token }
}
