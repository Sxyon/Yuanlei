/** 历史治理URL转到同项目可信页面，准确对象、修订与锚点保持。 */
export function projectWorkspaceIntent(route) {
  const query = { ...route.query },
    hash = route.hash || ''
  let name = 'ProjectTopics'
  if (
    query.task_id ||
    hash.startsWith('#tasks') ||
    hash.startsWith('#task-') ||
    hash.startsWith('#legacy-execution-')
  )
    name = 'ProjectPlans'
  else if (hash.startsWith('#blueprint')) name = 'ProjectBlueprints'
  else if (hash.startsWith('#reports')) name = 'ProjectReports'
  return { name, params: { project_id: route.params.project_id }, query, hash }
}
