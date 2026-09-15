import assert from 'node:assert/strict'
import test from 'node:test'

import { renderHtmlPreviewBlocks } from '../../src/utils/htmlPreviewRenderer.js'

const identity = (html) => html
const countMatches = (value, pattern) => value.match(pattern)?.length || 0

test('完整 HTML 预览块使用稳定尺寸并保留周边内容', () => {
  const result = renderHtmlPreviewBlocks(
    'before\n```html:preview\n<div>Hello</div>\n```\nafter',
    { sanitizeHtml: identity }
  )

  assert.ok(result.includes('html-preview-render'))
  assert.ok(result.includes('--html-preview-width: 800px'))
  assert.ok(result.includes('--html-preview-height: 360px'))
  assert.ok(result.includes('--html-preview-loading-height: 180px'))
  assert.ok(result.includes('--html-preview-min-height: 1px'))
  assert.ok(result.includes('--html-preview-max-height: 700px'))
  assert.ok(!result.includes('html-preview-header'))
  assert.ok(!result.includes('HTML 预览'))
  assert.ok(result.includes('html-preview-frame-slot'))
  assert.ok(result.includes('html-preview-srcdoc'))
  assert.ok(result.includes('&lt;div&gt;Hello&lt;/div&gt;'))
  assert.ok(!result.includes('<iframe'))
  assert.ok(!result.includes('```html:preview'))
  assert.ok(result.includes('before'))
  assert.ok(result.includes('after'))
})

test('普通 HTML 代码块与未闭合预览块保持流式安全', () => {
  const ordinary = renderHtmlPreviewBlocks('```html\n<div>Hello</div>\n```', {
    sanitizeHtml: identity
  })
  assert.ok(ordinary.includes('```html'))
  assert.ok(!ordinary.includes('html-preview-render'))

  const incomplete = renderHtmlPreviewBlocks('before\n```html:preview\n<div>', {
    sanitizeHtml: identity
  })
  assert.ok(incomplete.includes('html-preview-render'))
  assert.ok(incomplete.includes('html-preview-loading-slot'))
  assert.ok(incomplete.includes('html-preview-loading-canvas'))
  assert.ok(incomplete.includes('html-preview-skeleton-title'))
  assert.ok(incomplete.includes('html-preview-skeleton-card'))
  assert.ok(incomplete.includes('HTML 预览加载中'))
  assert.ok(!incomplete.includes('```html:preview'))
  assert.ok(!incomplete.includes('<div>'))
  assert.ok(!incomplete.includes('html-preview-frame-slot'))

  const malformed = renderHtmlPreviewBlocks('before\n```html:pre\n<div>', {
    sanitizeHtml: identity
  })
  assert.ok(malformed.includes('html-preview-render'))
  assert.ok(malformed.includes('html-preview-loading-slot'))
  assert.ok(!malformed.includes('```html:pre'))
  assert.ok(!malformed.includes('<div>'))

  const closedMalformed = renderHtmlPreviewBlocks('```html:pre\n<div>Keep code</div>\n```', {
    sanitizeHtml: identity
  })
  assert.ok(closedMalformed.includes('```html:pre'))
  assert.ok(closedMalformed.includes('<div>Keep code</div>'))
  assert.ok(!closedMalformed.includes('html-preview-render'))
})

test('HTML 预览支持多个大小写不敏感的 fenced blocks', () => {
  const multiple = renderHtmlPreviewBlocks(
    '```html:preview\n<section>A</section>\n```\ntext\n```html:preview\n<section>B</section>\n```',
    { sanitizeHtml: identity }
  )
  assert.equal(countMatches(multiple, /html-preview-render/g), 2)
  assert.equal(countMatches(multiple, /html-preview-frame-slot/g), 2)
  assert.ok(multiple.includes('text'))

  const uppercase = renderHtmlPreviewBlocks('~~~HTML:PREVIEW\n<div>Case</div>\n~~~', {
    sanitizeHtml: identity
  })
  assert.ok(uppercase.includes('html-preview-render'))
  assert.ok(uppercase.includes('&lt;div&gt;Case&lt;/div&gt;'))
})

test('HTML preview blocks preserve special characters and sanitized content', () => {
  const specialCharacters = renderHtmlPreviewBlocks(
    '```html:preview\n<div title="`code`">\n\n<span>Line</span>\n</div>\n```',
    { sanitizeHtml: identity }
  )
  assert.ok(specialCharacters.includes('html-preview-render'))
  assert.ok(specialCharacters.includes('`code`'))
  assert.ok(specialCharacters.includes('&#10;&#10;'))
  assert.ok(specialCharacters.includes('&lt;span&gt;Line&lt;/span&gt;'))

  const documentBlock = renderHtmlPreviewBlocks(
    '```html:preview\n<!doctype html>\n<html><head><style>.card{display:grid;color:red}</style></head><body><div class="card">Styled</div></body></html>\n```',
    { sanitizeHtml: identity }
  )
  assert.ok(documentBlock.includes('&lt;style&gt;.card{display:grid;color:red}&lt;/style&gt;'))
  assert.ok(documentBlock.includes('&lt;div class=&quot;card&quot;&gt;Styled&lt;/div&gt;'))

  const sanitized = renderHtmlPreviewBlocks(
    '```html:preview\n<div>safe</div><script>alert(1)</script>\n```',
    { sanitizeHtml: () => '<div>safe</div>' }
  )
  assert.ok(sanitized.includes('&lt;div&gt;safe&lt;/div&gt;'))
  assert.ok(!sanitized.includes('alert(1)'))
})

test('流式 HTML 预览使用正式预览一半的 loading 高度', () => {
  const result = renderHtmlPreviewBlocks('```html:preview\n<div>')
  assert.match(result, /--html-preview-height: 360px/)
  assert.match(result, /--html-preview-loading-height: 180px/)
  assert.match(result, /html-preview-loading-slot/)
})
