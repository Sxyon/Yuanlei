const storageKey = 'yuanlei-governance-drafts'
const drafts = new Map()
const key = (user, project, object) => JSON.stringify([user, project, object])
try {
  for (const [id, value] of Object.entries(JSON.parse(sessionStorage.getItem(storageKey) || '{}'))) {
    try {
      const scope = JSON.parse(id)
      if (Array.isArray(scope) && scope.length === 3 && scope.every(part => typeof part === 'string' && part) && value && typeof value === 'object') drafts.set(id, value)
    } catch { /* 损坏的单个缓存项不影响其他草稿。 */ }
  }
} catch { /* 会话存储不可用时仍在当前标签页保留草稿。 */ }
function persist() {
  try {
    if (drafts.size) sessionStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(drafts)))
    else sessionStorage.removeItem(storageKey)
  } catch { /* 不阻断真实业务操作。 */ }
}
/** 恢复本人准确对象上的短期草稿副本。 */
export function getGovernanceDraft(user, project, object) {
  const value = user && drafts.get(key(user, project, object))
  return value ? JSON.parse(JSON.stringify(value)) : null
}
export function setGovernanceDraft(user, project, object, value) {
  if (!user) return
  if (value) drafts.set(key(user, project, object), JSON.parse(JSON.stringify(value)))
  else drafts.delete(key(user, project, object))
  persist()
}
/** 无权时清除项目草稿，登出时清除全部身份的草稿。 */
export function clearGovernanceDrafts(user, project) {
  if (!user) drafts.clear()
  else for (const id of drafts.keys()) {
    const [owner, scope] = JSON.parse(id)
    if (owner === user && scope === project) drafts.delete(id)
  }
  persist()
}
