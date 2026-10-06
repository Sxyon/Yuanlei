/** 模板仅用于新文档起草，保存仍使用普通 Markdown 文件接口。 */
export const blueprintTemplates = [
  { value: 'blank', label: '空白' },
  { value: 'ongoing', label: '长期经营' },
  { value: 'delivery', label: '阶段交付' }
]

export function blueprintTemplateContent(type) {
  if (type === 'blank') return ''
  const ongoing = type === 'ongoing'
  return `# ${ongoing ? '长期经营方向' : '阶段交付蓝图'}

## 预期结果
${ongoing ? '- 希望持续改善的业务结果：' : '- 本阶段要交付的结果及范围：'}
- 对谁产生什么价值：

## 衡量方式
- 如何判断结果达成：
- 观察指标、基线与目标：
- 可核对的证据：

## 时间与复盘
${ongoing ? '- 观察周期与下次复盘时间：' : '- 计划交付时间与阶段检查点：'}
- 复盘时要回答的问题：

## 约束
- 资源、预算与依赖：
- 必须遵守的条件及不做的事项：

## 当前重点
- 最先推进的事项：
- 待澄清的问题与风险：
`
}
