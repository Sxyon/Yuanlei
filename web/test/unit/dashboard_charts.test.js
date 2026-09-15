import test from 'node:test'
import assert from 'node:assert/strict'
import { use } from 'echarts/core'
import { SVGRenderer } from 'echarts/renderers'
import { init } from '../../src/utils/dashboardCharts.js'

test('Dashboard 按需注册支持柱线饼图、滚动图例及坐标系', () => {
  use(SVGRenderer)
  const chart = init(null, null, { renderer: 'svg', ssr: true, width: 600, height: 400 })
  try {
    chart.setOption({
      tooltip: {},
      legend: { type: 'scroll' },
      grid: {},
      xAxis: { type: 'category', data: ['A', 'B'] },
      yAxis: {},
      series: [
        { type: 'bar', name: 'bars', data: [2, 3] },
        { type: 'line', name: 'lines', data: [3, 4] },
        { type: 'pie', name: 'pie', radius: 30, data: [{ name: 'slice', value: 5 }] }
      ]
    })
    assert.deepEqual(
      chart.getOption().series.map((series) => series.type),
      ['bar', 'line', 'pie']
    )
    const svg = chart.renderToSVGString()
    assert.match(svg, /<path/)
    for (const label of ['bars', 'lines', 'slice']) assert.ok(svg.includes(label))
  } finally {
    chart.dispose()
  }
})
