import assert from 'node:assert/strict'
import test from 'node:test'
import { readThemePreview, themePreviewQuery, themePreviewTarget, supportsWorkspacePreview } from '../../src/utils/projectThemePreview.js'

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
  assert.equal(supportsWorkspacePreview({theme:{baseVersion:1,pages:[{capability:'overview'},{blocks:[]}]}}),false)
})
