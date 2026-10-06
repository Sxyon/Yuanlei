import assert from 'node:assert/strict'
import test from 'node:test'

import { fillProjectNameFromFolder, filterProjects, formatRelativeTime } from '../../src/utils/projectSelection.js'

test('Project 搜索按名称过滤且无匹配时返回空列表', () => {
  const projects = [{ name: 'Desktop' }, { name: '论文写作' }, { name: 'Agent Skills' }]

  assert.deepEqual(filterProjects(projects, '  agent  '), [{ name: 'Agent Skills' }])
  assert.deepEqual(filterProjects(projects, '不存在'), [])
  assert.equal(filterProjects(projects, ''), projects)
})

test('新建文件夹后按互补规则补齐项目名称', () => {
  assert.equal(fillProjectNameFromFolder('', '资料归档'), '资料归档')
  assert.equal(fillProjectNameFromFolder('   ', '  资料归档  '), '资料归档')
  assert.equal(fillProjectNameFromFolder('产品发布计划', '资料归档'), '产品发布计划')
  assert.equal(fillProjectNameFromFolder('', ''), '')
  assert.equal(fillProjectNameFromFolder('', 'x'.repeat(150)), 'x'.repeat(100))
})

test('历史项目时间按分钟到年份显示相对时间', () => {
  const now = Date.parse('2026-08-22T12:00:00Z')

  assert.equal(formatRelativeTime('2026-08-22T11:59:30Z', now), '刚刚')
  assert.equal(formatRelativeTime('2026-08-22T11:55:00Z', now), '5分钟前')
  assert.equal(formatRelativeTime('2026-08-22T09:00:00Z', now), '3小时前')
  assert.equal(formatRelativeTime('2026-08-19T12:00:00Z', now), '3天前')
  assert.equal(formatRelativeTime('2026-06-22T12:00:00Z', now), '2个月前')
  assert.equal(formatRelativeTime('2024-08-22T12:00:00Z', now), '2年前')
  assert.equal(formatRelativeTime('invalid', now), '')
})


test('项目类型分类标签组合筛选，缺设置旧项目默认未指定且清除显示全部', () => {
  const projects = [
    { id: 'legacy', name: '旧项目' },
    { id: 'ongoing', name: '经营', project_type: 'ongoing', category: '业务', tags: ['收入', '复盘'] },
    { id: 'delivery', name: '交付', project_type: 'delivery', category: '业务', tags: ['复盘'] }
  ]
  assert.deepEqual(filterProjects(projects, '', { type: 'unspecified' }).map(p => p.id), ['legacy'])
  assert.deepEqual(filterProjects(projects, '', { category: '业务', tag: '收入' }).map(p => p.id), ['ongoing'])
  assert.deepEqual(filterProjects(projects, '', { type: 'delivery', category: '业务', tag: '收入' }), [])
  assert.equal(filterProjects(projects, '', {}), projects)
  assert.deepEqual(projects[0], { id: 'legacy', name: '旧项目' })
})
