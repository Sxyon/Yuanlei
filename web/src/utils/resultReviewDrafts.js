import { ref } from 'vue'

const storageKey = 'yuanlei-result-review-drafts'
function read() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(storageKey) || '{}')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch { return {} }
}
export const reviewDrafts = ref(read())
const key = (user, project, task, result) => JSON.stringify([user, project, task, result])
function persist() {
  try {
    if (Object.keys(reviewDrafts.value).length) sessionStorage.setItem(storageKey, JSON.stringify(reviewDrafts.value))
    else sessionStorage.removeItem(storageKey)
  } catch { /* 当前页仍保留意见，存储不可用时不阻断办理。 */ }
}
/** 只恢复已认证用户在准确结果上的短期意见。 */
export function getReviewDraft(user, project, task, result) {
  return user ? reviewDrafts.value[key(user, project, task, result)] || '' : ''
}
export function setReviewDraft(user, project, task, result, comment) {
  if (!user) return
  const id = key(user, project, task, result)
  if (comment) reviewDrafts.value[id] = comment
  else delete reviewDrafts.value[id]
  persist()
}
/** 无权访问时撤销该对象及子结果的本地意见。 */
export function clearReviewScope(user, project, task) {
  for (const id of Object.keys(reviewDrafts.value)) {
    try {
      const [owner, scope, object] = JSON.parse(id)
      if (owner === user && scope === project && (!task || object === task)) delete reviewDrafts.value[id]
    } catch { delete reviewDrafts.value[id] }
  }
  persist()
}
export function clearReviewDrafts() {
  reviewDrafts.value = {}
  try { sessionStorage.removeItem(storageKey) } catch { /* 登出仍清空内存。 */ }
}
