import { apiGet, apiPost, apiPut, apiRequest } from './base'

/** 独立项目工作任务。 */
export const projectWorkApi = {
  listTasks: (projectId) => apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks`),
  getCode: (projectId) => apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/code`),
  configureCode: (projectId, code) =>
    apiPut(`/api/projects/${encodeURIComponent(projectId)}/work/code`, { code }),
  createTask: (projectId, payload) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks`, payload),
  getTask: (projectId, taskId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}`),
  updateTask: (projectId, taskId, payload) =>
    apiRequest(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH', body: JSON.stringify(payload)
    }),
  addReference: (projectId, taskId, payload) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/references`, payload),
  removeReference: (projectId, taskId, referenceId) =>
    apiRequest(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/references/${encodeURIComponent(referenceId)}`, {
      method: 'DELETE'
    }),
  createIssue: (projectId, taskId, payload) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/issues`, payload),
  getIssue: (projectId, taskId, issueId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/issues/${encodeURIComponent(issueId)}`),
  updateIssue: (projectId, taskId, issueId, status) =>
    apiRequest(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/issues/${encodeURIComponent(issueId)}`, {
      method: 'PATCH', body: JSON.stringify({ status })
    }),
  addIssueComment: (projectId, taskId, issueId, content) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/issues/${encodeURIComponent(issueId)}/comments`, { content }),
  addComment: (projectId, taskId, content) =>
    apiPost(
      `/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/comments`,
      { content }
    )
}
