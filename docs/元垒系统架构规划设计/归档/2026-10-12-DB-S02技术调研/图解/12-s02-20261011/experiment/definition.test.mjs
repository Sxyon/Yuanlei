import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { validateDefinition } from './definition.mjs'

const read = name => JSON.parse(readFileSync(new URL(`./themes/${name}.json`, import.meta.url)))
test('两个主题各有两页，按同一有限词汇通过验证', () => {
  for (const name of ['default', 'research']) assert.equal(validateDefinition(read(name)).pages.length, 2)
})
for (const [name, mutate, reason] of [
  ['未知组件', d => { d.pages[0].blocks[0].type = 'execute-js' }, 'unknown_component'],
  ['任意请求路径', d => { d.pages[0].blocks[0].binding = '../secret' }, 'binding_not_declared'],
  ['脚本字段', d => { d.pages[0].blocks[0].script = 'fetch("/api")' }, 'unknown_field'],
  ['重复页面', d => { d.pages[1].id = d.pages[0].id }, 'invalid_page'],
  ['未支持布局', d => { d.layout = 'javascript' }, 'invalid_metadata'],
  ['记录列表误绑单个项目', d => { d.pages[0].blocks[0].type = 'records' }, 'invalid_block'],
  ['错误文件格式', d => { d.pages[0].blocks[0] = { type: 'image', binding: 'report', title: '错误类型' } }, 'invalid_block'],
  ['非页面数组', d => { d.pages = 'eval()' }, 'invalid_pages'],
  ['过量组件', d => { d.pages[0].blocks = Array(13).fill(d.pages[0].blocks[0]) }, 'invalid_blocks']
]) test(`${name}因正确原因拒绝`, () => {
  const value = read('default'); mutate(value)
  assert.throws(() => validateDefinition(value), new RegExp(reason))
})
