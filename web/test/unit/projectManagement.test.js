import assert from 'node:assert/strict'
import test from 'node:test'
import { searchManagedProjects } from '../../src/utils/projectManagement.js'

test('搜索可见项目的标识、描述和分类标签，按更新时间与UUID排序且不修改来源', () => {
  const projects = [
    {id: 'z', name: '同名', slug: 'A', description: '工坊', updated_at: '2026-10-11'},
    {id: 'a', name: '同名', category: '运营', tags: ['里程碑'], updated_at: '2026-10-11'},
    {id: 'old', name: '旧项目', updated_at: '2026-10-01'}
  ]
  assert.deepEqual(searchManagedProjects(projects, ' a ').map(p => p.id), ['z'])
  assert.deepEqual(searchManagedProjects(projects, '工坊').map(p => p.id), ['z'])
  assert.deepEqual(searchManagedProjects(projects, '里程碑').map(p => p.id), ['a'])
  assert.deepEqual(searchManagedProjects(projects, '运营').map(p => p.id), ['a'])
  assert.deepEqual(searchManagedProjects(projects, '').map(p => p.id), ['a', 'z', 'old'])
  assert.deepEqual(searchManagedProjects(projects, '无匹配'), [])
  assert.deepEqual(projects.map(p => p.id), ['z', 'a', 'old'])
})
