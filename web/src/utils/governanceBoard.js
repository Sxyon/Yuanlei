/**
 * 督查板展示适配：只读取 board 读视图已计算好的字段（pending_*、blocked_runs、
 * run_status_counts），不自行重建 Run 或治理状态。状态映射仅是文案本地化。
 */

export const RUN_STATUS_LABELS = {
  dispatching: '提交中',
  submitted: '已提交',
  queued: '排队中',
  dispatched: '已派发',
  pending: '等待中',
  running: '运行中',
  completed: '已完成',
  skipped: '已跳过',
  failed: '失败',
  rejected: '已拒绝',
  cancelled: '已取消',
  interrupted: '已中断'
}

export const GOVERNANCE_STATUS_LABELS = {
  proposed: '待审核',
  canonical: '已确认',
  rejected: '已拒绝',
  implemented: '已实施'
}

export const GOVERNANCE_STATUS_COLORS = {
  proposed: 'gold',
  canonical: 'green',
  rejected: 'red',
  implemented: 'green'
}

export const SOURCE_CHANNEL_LABELS = {
  project: '项目内',
  multica: 'Multica',
  github: 'GitHub',
  gitea: 'Gitea'
}

/** 展示 Run 状态中文文案，未知状态回退为原始值。 */
export function runStatusLabel(status) {
  return RUN_STATUS_LABELS[status] || status
}

/** 展示治理状态中文文案，未知状态回退为原始值。 */
export function governanceStatusLabel(status) {
  return GOVERNANCE_STATUS_LABELS[status] || status
}

/** 展示治理状态配色，只按后端状态串查表，未知状态回退为待定色。 */
export function governanceStatusColor(status) {
  return GOVERNANCE_STATUS_COLORS[status] || 'gold'
}

/** 展示来源渠道文案，未知渠道回退为原始值。 */
export function sourceChannelLabel(channel) {
  return SOURCE_CHANNEL_LABELS[channel] || channel
}

/**
 * 把读视图返回的 run_status_counts 转为仅展示的非零条目，按数量倒序。
 * 不做任何状态判断，计数与状态名都来自后端。
 */
export function runStatusEntries(runStatusCounts) {
  if (!runStatusCounts || typeof runStatusCounts !== 'object') return []
  return Object.entries(runStatusCounts)
    .filter(([, count]) => Number(count) > 0)
    .map(([status, count]) => ({ status, label: runStatusLabel(status), count: Number(count) }))
    .sort((left, right) => right.count - left.count || left.status.localeCompare(right.status))
}

/** 提取督查板加载失败的可展示文案。 */
export function describeBoardError(error) {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (detail && typeof detail === 'object') return detail.message || '督查板加载失败'
  return error?.message || '督查板加载失败'
}

/** 纳入资格与研讨进度各自展示。 */
export function topicAdmissionLabel(status) {
  return { proposed: '待纳入', canonical: '已纳入', rejected: '拒绝纳入' }[status] || status
}

export function topicProgressLabel(progress) {
  return { open: '研讨中', decided: '已形成决策', closed: '已关闭' }[progress] || progress
}
