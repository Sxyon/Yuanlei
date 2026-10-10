import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { collaborationObjectAction, resolveCollaborationObject } from './contracts.js'
const cases = JSON.parse(await readFile(new URL('../../../docs/元垒系统架构规划设计/第一阶段专项/样例/collaboration-read-v1-joint.json', import.meta.url), 'utf8')).examples
for (const sample of cases) {
  const projection = sample.projection
  for (const action of projection.allowed_actions) {
    const resolved = collaborationObjectAction(projection, action, sample.host_return.token)
    assert.equal(resolved.type, 'open-object')
    assert.equal(resolved.attempt_id, action.attempt_id)
    assert.equal(resolved.question_revision, action.question_revision)
    assert.equal(resolved.result_id, action.result_id)
    assert.ok(!('source_route' in resolved))
    const object = { ...resolved }
    const opened = resolveCollaborationObject(resolved, [object], sample.host_return)
    assert.equal(opened.object_ref.attempt_id, action.attempt_id)
    assert.throws(() => resolveCollaborationObject({ ...resolved, project_id: 'wrong' }, [object], sample.host_return), /object_not_visible_or_stale/)
    assert.throws(() => resolveCollaborationObject({ ...resolved, question_revision: 999 }, [object], sample.host_return), /object_not_visible_or_stale/)
    assert.throws(() => resolveCollaborationObject({ ...resolved, return_token: 'expired' }, [object], sample.host_return), /return_token_invalid/)
  }
  assert.throws(() => collaborationObjectAction(projection, { ...projection.allowed_actions[0], project_id: 'other' }, sample.host_return.token), /object_scope_mismatch/)
  assert.throws(() => collaborationObjectAction(projection, projection.allowed_actions[0], null), /return_token_required/)
}
console.log('Five joint projection scenarios mapped to exact host object descriptors; synthetic-only, server authorization Not run')
