import assert from 'node:assert/strict'
import test from 'node:test'
import { displayBlueprintName, normalizeBlueprintName } from '../../src/utils/blueprintName.js'

test('新建蓝图自动补全后缀，界面隐藏后缀', () => {
  assert.equal(normalizeBlueprintName('  product-plan  '), 'product-plan.md')
  assert.equal(normalizeBlueprintName('product-plan.md'), 'product-plan.md')
  assert.equal(normalizeBlueprintName('API.MD'), 'API.md')
  assert.equal(displayBlueprintName('product-plan.md'), 'product-plan')
})

test('无效名称在进入 HTTP 创建前被拒绝', () => {
  for (const name of ['', '../escape', 'folder/plan', 'plan name', 'a'.repeat(121)])
    assert.equal(normalizeBlueprintName(name), null)
})

test('名称支持大写英文与常用标点，拒绝空白和危险字符', () => {
  for (const name of [
    'API设计（第二版）',
    '产品方案：用户端',
    '阶段一、阶段二',
    '方案A+B',
    '需求&验收',
    'v1.2_接口设计-修订版'
  ])
    assert.equal(normalizeBlueprintName(name), `${name}.md`)
  for (const name of [
    'a b',
    'a\tb',
    'a\nb',
    'a:b',
    'a*b',
    'a?b',
    'a"b',
    'a<b',
    'a>b',
    'a|b',
    '中'.repeat(65)
  ])
    assert.equal(normalizeBlueprintName(name), null)
})
