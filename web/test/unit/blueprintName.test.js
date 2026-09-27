import assert from 'node:assert/strict'
import test from 'node:test'
import { displayBlueprintName, normalizeBlueprintName } from '../../src/utils/blueprintName.js'

test('新建蓝图自动补全后缀，界面隐藏后缀', () => {
  assert.equal(normalizeBlueprintName('  product-plan  '), 'product-plan.md')
  assert.equal(normalizeBlueprintName('product-plan.md'), 'product-plan.md')
  assert.equal(displayBlueprintName('product-plan.md'), 'product-plan')
})

test('无效名称在进入 HTTP 创建前被拒绝', () => {
  for (const name of ['', '../escape', 'folder/plan', 'Plan', 'plan.MD', 'a'.repeat(121)])
    assert.equal(normalizeBlueprintName(name), null)
})
