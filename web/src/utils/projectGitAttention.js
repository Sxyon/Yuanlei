import { projectApi } from '@/apis/project_api'

/** 服务器先筛待人工审批再分页；不从最近历史猜待办。 */
export async function loadProjectGitAttention(projectId, section = 'all') {
  const pendingRequest = section === 'occupancies' ? Promise.resolve([]) : (async () => {
    const rows = []
    for (let offset = 0; ; offset += 100) {
      const page = await projectApi.getGitActions(projectId, { status: 'pending', limit: 100, offset })
      rows.push(...page.filter(row => row.status === 'pending'))
      if (page.length < 100) break
    }
    return [...new Map(rows.map(row => [row.id, row])).values()]
  })()
  const [occupancies, pending] = await Promise.all([section === 'approvals' ? Promise.resolve([]) : projectApi.getGitOccupancies(projectId), pendingRequest])
  return { occupancies: occupancies.filter(row => ['owned', 'queued'].includes(row.status)), pending }
}
