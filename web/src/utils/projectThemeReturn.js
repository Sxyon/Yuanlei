/** 返回令牌只持有宿主捕获的上下文，目的路由始终由平台生成。 */
export function saveThemeReturn(userId, context) {
  const token = crypto.randomUUID()
  sessionStorage.setItem('project-theme-return', JSON.stringify({ token, userId: String(userId), context }))
  return token
}

/** 同账号同项目读取；版本及绑定修订由加载后的宿主再次核对。 */
export function readThemeReturn(token, userId, projectId) {
  try {
    const saved = JSON.parse(sessionStorage.getItem('project-theme-return'))
    return typeof token === 'string' && saved?.token === token && saved.userId === String(userId) && saved.context?.projectId === projectId ? saved.context : null
  } catch { return null }
}

/** 返回地址不接受浏览器提供的URL，只能回当前项目主题。 */
export function themeReturnTarget(token, userId, projectId) {
  return readThemeReturn(token, userId, projectId) ? { name: 'ProjectThemeDisplay', params: { project_id: projectId }, query: { theme_return: token } } : null
}
