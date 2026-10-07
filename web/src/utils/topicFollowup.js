/** 为准确引用生成可选键；版本变化不会误选新版本。 */
export const candidateKey = (item) =>
  JSON.stringify({ kind: item.kind, id: item.id, version: item.version })
const statuses = {
  draft: '草案',
  approved: '已批准',
  superseded: '已替代',
  revoked: '已撤销',
  pending: '待验收',
  accepted: '已接受',
  not_accepted: '未接受'
}
/** 候选照实显示当前状态。 */
export const candidateTitle = (item) =>
  `${item.title} · 版本${item.version}${item.status ? ` · ${statuses[item.status] || item.status}` : ''}`
/** 引用始终指向提交时版本。 */
export const referenceLabel = (item) =>
  `${{ revision: '议题修订', decision: '决策', result: '工作结果' }[item.kind]} ${item.version}${item.snapshot?.current_status_at_recording ? ` · 引用时${statuses[item.snapshot.current_status_at_recording]}` : ''}`
/** 展示冻结正文，不让维护页当前内容覆盖当时依据。 */
export const snapshotText = (item) => {
  const value = item.snapshot || {}
  return (
    [
      value.title,
      value.summary,
      value.conclusion,
      value.rationale,
      value.expected_outcome,
      value.verification_conditions
    ]
      .filter(Boolean)
      .join('\n\n') || '未记录正文'
  )
}
/** 响应丢失后的原意图重试沿用标识；内容或版本改变使用新标识。 */
export function stableIntent(draft, payload) {
  const key = JSON.stringify(payload)
  if (draft.intent !== key) {
    draft.intent = key
    draft.operationId = crypto.randomUUID()
  }
  return { ...payload, operation_id: draft.operationId }
}
/** 只有目标或条件变更提示旧确认；纯正文修订保留对应修订标识。 */
export function confirmationConditionsChanged(topic, record) {
  return (
    !!record &&
    (topic.expected_outcome !== record.expected_outcome ||
      topic.verification_conditions !== record.verification_conditions)
  )
}

/** 候选刷新后仍提交原选择的准确版本，由后端拒绝过期或无效引用。 */
export const selectedReference = (key) => (key ? JSON.parse(key) : null)

/** 成功响应消费本次标识；再发同样正文是新的操作，失败重试仍保留旧标识。 */
export function consumeIntent(draft, operationId) {
  if (draft.operationId === operationId) {
    delete draft.intent
    delete draft.operationId
  }
}
