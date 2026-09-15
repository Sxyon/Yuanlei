import assert from 'node:assert/strict'
import test from 'node:test'

import { renderSvgBlocks } from '../../src/utils/svgRenderer.js'

test('SVG fenced blocks render safely with controls and preserve other content', () => {
  {
    const result = renderSvgBlocks('before\n```svg\n<svg><circle/></svg>\n```\nafter')
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('<svg>'))
    assert.ok(!result.includes('```svg'))
    assert.ok(result.includes('before'))
    assert.ok(result.includes('after'))
    assert.ok(result.includes('svg-actions'))
    assert.ok(result.includes('svg-copy-btn'))
    assert.ok(result.includes('svg-png-btn'))
    assert.ok(result.includes('复制 SVG'))
    assert.ok(result.includes('复制为 PNG'))
  }

  {
    const result = renderSvgBlocks('~~~svg\n<svg><rect/></svg>\n~~~')
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('<rect/>'))
  }

  {
    const result = renderSvgBlocks(
      '```svg\n<svg>\n<defs>\n<linearGradient id="g">\n<stop offset="0%"/>\n\n<stop offset="100%"/>\n</linearGradient>\n</defs>\n</svg>\n```'
    )
    const lines = result.split('\n')
    assert.equal(lines.length, 1)
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('<stop offset="0%"/><stop offset="100%"/>'))
    assert.ok(result.includes('svg-copy-btn'))
  }

  {
    const result = renderSvgBlocks('```SVG\n<svg/>\n```')
    assert.ok(result.includes('svg-inline-render'))
  }

  {
    const result = renderSvgBlocks('before\n```svg\n<svg>')
    assert.ok(result.includes('```svg'))
    assert.ok(!result.includes('svg-inline-render'))
    assert.ok(result.includes('before'))
  }

  {
    const result = renderSvgBlocks('```python\nprint(1)\n```')
    assert.ok(result.includes('```python'))
    assert.ok(result.includes('```'))
    assert.ok(!result.includes('svg-inline-render'))
  }

  {
    const result = renderSvgBlocks('```svg\n<svg id="1"/>\n```\ntext\n```svg\n<svg id="2"/>\n```')
    const matches = result.match(/svg-inline-render/g)
    assert.equal(matches ? matches.length : 0, 2)
    const btnMatches = result.match(/svg-copy-btn/g)
    assert.equal(btnMatches ? btnMatches.length : 0, 2)
    assert.ok(result.includes('text'))
  }

  {
    const result = renderSvgBlocks('```svg\n```')
    assert.ok(result.includes('svg-inline-render'))
  }

  {
    const result = renderSvgBlocks('hello world\n\nsome text')
    assert.equal(result, 'hello world\n\nsome text')
  }

  {
    const result = renderSvgBlocks('```svg\n<svg><title>`code`</title></svg>\n```')
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('`code`'))
  }

  {
    const result = renderSvgBlocks('```svg id="mySvg"\n<svg/>\n```')
    assert.ok(result.includes('svg-inline-render'))
  }

  {
    const result = renderSvgBlocks('```svg\n<svg/>\n```\n\nsome text after')
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('some text after'))
  }

  {
    const result = renderSvgBlocks('some text before\n\n```svg\n<svg/>\n```')
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('some text before'))
  }

  {
    const result = renderSvgBlocks(
      '# Title\n\n```svg\n<svg id="a"/>\n```\n\nSome text\n\n```svg\n<svg id="b"/>\n```\n\n# End'
    )
    const matches = result.match(/svg-inline-render/g)
    assert.equal(matches ? matches.length : 0, 2)
    assert.ok(result.includes('# Title'))
    assert.ok(result.includes('Some text'))
    assert.ok(result.includes('# End'))
  }

  {
    const result = renderSvgBlocks('```svg\n<svg><!-- comment --><circle/></svg>\n```')
    assert.ok(result.includes('svg-inline-render'))
    assert.ok(result.includes('svg-copy-btn'))
    assert.ok(result.includes('<!-- comment -->'))
  }

  {
    const result = renderSvgBlocks('```svg\n<svg viewBox="0 0 100 50"><circle/></svg>\n```')
    assert.ok(result.includes('svg-actions'))
    assert.ok(result.includes('svg-copy-btn'))
    assert.ok(result.includes('svg-png-btn'))
    assert.ok(result.includes('type="button"'))
    assert.ok(result.includes('复制 SVG'))
    assert.ok(result.includes('复制为 PNG'))
    const actionsIdx = result.indexOf('svg-actions')
    const svgIdx = result.indexOf('<svg ')
    assert.ok(actionsIdx < svgIdx)
  }
})
