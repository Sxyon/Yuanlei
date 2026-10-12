import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { compilePage } from './schema.mjs'
const definition = JSON.parse(fs.readFileSync(new URL('../themes/default.json', import.meta.url)))
test('标题中的表达式保留原始值，Schema只引用固定可信组件', () => {
  const theme = structuredClone(definition)
  theme.pages[0].blocks[0].title = '$get(secret)'
  const schema = compilePage(theme, theme.pages[0].id, {}, {}, () => {})
  assert.equal(schema[0].$cmp, 'ThemeBlock')
  assert.equal(schema[0].props.__raw__block.title, '$get(secret)')
  assert.equal(Object.hasOwn(schema[0], '$el'), false)
})
test('拒绝用户直接注入原生FormKit节点及事件属性', () => {
  for (const payload of [{ $el: 'script', children: 'probe' }, { attrs: { onClick: 'probe' } }, { $cmp: 'Unknown' }]) {
    const theme = structuredClone(definition)
    Object.assign(theme.pages[0].blocks[0], payload)
    assert.throws(() => compilePage(theme, theme.pages[0].id, {}, {}, () => {}), /unknown_field/)
  }
})
test('拒绝未声明页面', () => {
  assert.throws(() => compilePage(definition, 'secret', {}, {}, () => {}), /page_not_declared/)
})
