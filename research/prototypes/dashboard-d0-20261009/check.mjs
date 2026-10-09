import fs from 'node:fs'
import assert from 'node:assert/strict'
import { inspectDefinition } from './contracts.js'
const x = JSON.parse(fs.readFileSync(new URL('./examples.json', import.meta.url)))
for (const t of [...x.templates, x.autonomous]) {
  assert.deepEqual(inspectDefinition(t.definition, {}, x.materials), [], t.id)
  assert.ok(t.definition.inputs.length > 0)
  assert.ok(t.definition.layout.children.length > 1)
}
const sorted = es => es.map(e => `${e.pointer}:${e.code}`).sort()
assert.deepEqual(sorted(inspectDefinition(x.illegal.definition, x.illegal.bindings, x.materials)), sorted(x.expected_errors))
const bad = structuredClone(x.templates[0].definition); bad.schema_version = 99
assert.ok(inspectDefinition(bad, {}, x.materials).some(e => e.code === 'unsupported_schema'))
assert.equal(x.templates[0].definition.layout.children[0].mapping.value, 'totals.total_results')
assert.notDeepEqual(x.business_bindings.alpha, x.business_bindings.beta)
assert.equal(x.autonomous.definition.layout.kind, 'stack')
assert.equal(x.templates[0].definition.layout.kind, 'grid')
console.log('PASS: 3 合法定义、5 精确非法位置、未知版本拒绝、指标映射、独立绑定和结构差异。仅合成结构检查。')
