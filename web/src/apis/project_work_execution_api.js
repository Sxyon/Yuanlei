import { apiGet, apiPost } from './base'

/** 项目任务分配与数字员工工作台。 */
export const projectWorkExecutionApi = {
  assign: (projectId, taskId, agentSlug) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/executions`, {
      agent_slug: agentSlug
    }),
  listForTask: (projectId, taskId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/executions`),
  getWorkbench: (projectId, agentSlug) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(agentSlug)}/workbench`),
  accept: (projectId, agentSlug, executionId) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(agentSlug)}/workbench/${encodeURIComponent(executionId)}/accept`, {}),
  cancel: (projectId, taskId, executionId) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/executions/${encodeURIComponent(executionId)}/cancel`, {})
}
