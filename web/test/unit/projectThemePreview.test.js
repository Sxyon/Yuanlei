import assert from 'node:assert/strict'
import test from 'node:test'
import { readThemePreview, readThemePreviewFiles, themePreviewQuery, themePreviewTarget, supportsWorkspacePreview } from '../../src/utils/projectThemePreview.js'

test('预览引用只允许准确版本或准确候选修订，不接受混合及数组意图',()=>{
  assert.equal(readThemePreview({}),null)
  assert.deepEqual(readThemePreview({theme_preview_version:'v'}),{versionId:'v'})
  assert.deepEqual(readThemePreview({theme_preview_source:'s',theme_preview_revision:'2'}),{sourceId:'s',revision:2})
  for(const query of [{theme_preview_version:['v']},{theme_preview_version:'v',theme_preview_source:'s'},{theme_preview_source:'s'},{theme_preview_source:'s',theme_preview_revision:'0'},{theme_preview_source:'s',theme_preview_revision:'1.2'}])assert.throws(()=>readThemePreview(query),/预览引用/)
  assert.deepEqual(themePreviewTarget('project',{versionId:'v'}),{name:'ProjectDashboardComp',params:{project_id:'project'},query:{theme_preview_version:'v'}})
  assert.deepEqual(themePreviewQuery({sourceId:'s',revision:2}),{theme_preview_source:'s',theme_preview_revision:'2'})
})
test('完整可信能力包进入同一项目页面，旧区块包保持明确的结构预览',()=>{
  assert.equal(supportsWorkspacePreview({theme:{baseVersion:1,pages:[{capability:'overview'}]}}),true)
  assert.equal(supportsWorkspacePreview({theme:{pages:[{blocks:[]}]}}),false)
  assert.equal(supportsWorkspacePreview({theme:{baseVersion:1,pages:[{capability:'overview'},{blocks:[]}]}}),true)
})

test('混合真实预览携未提交文件映射，准确候选仍绑定revision',()=>{
  const files={evidence:'/evidence/data.json'}
  assert.deepEqual(themePreviewQuery({sourceId:'s',revision:3,files}),{theme_preview_source:'s',theme_preview_revision:'3',theme_preview_files:JSON.stringify(files)})
  assert.deepEqual(files,{evidence:'/evidence/data.json'})
})

test('临时文件映射拒绝数组、非字符串与损坏JSON',()=>{
  assert.equal(readThemePreviewFiles({}),null)
  assert.deepEqual(readThemePreviewFiles({theme_preview_files:'{"facts":"/facts.json"}'}),{facts:'/facts.json'})
  for(const value of [[], '{}broken','[]','null','{"facts":3}']) assert.throws(()=>readThemePreviewFiles({theme_preview_files:value}))
})
