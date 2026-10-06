import { apiGet, apiPost, apiPut } from './base'

/** 项目任务分配与数字员工工作台。 */
export const projectWorkExecutionApi = {
  assign: (projectId, taskId, agentSlug, context = null) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/executions`, {
      agent_slug: agentSlug,
      ...(context ? { context } : {})
    }),
  previewContext: (projectId, taskId, selection) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/context/preview`, { selection }),
  getContext: (projectId, taskId, kind, recordId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/context/${encodeURIComponent(kind)}/${encodeURIComponent(recordId)}`),
  listForTask: (projectId, taskId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/executions`),
  getWorkbench: (projectId, agentSlug) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(agentSlug)}/workbench`),
  updateWorkbenchConfig: (projectId, agentSlug, config) =>
    apiPut(`/api/projects/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(agentSlug)}/workbench/config`, config),
  accept: (projectId, agentSlug, executionId) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/agents/${encodeURIComponent(agentSlug)}/workbench/${encodeURIComponent(executionId)}/accept`, {}),
  cancel: (projectId, taskId, executionId) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/executions/${encodeURIComponent(executionId)}/cancel`, {})
}
