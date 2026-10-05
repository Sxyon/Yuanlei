import { apiGet, apiPost, apiPut, apiRequest } from './base'

/** 独立项目工作任务。 */
export const projectWorkApi = {
  listTasks: (projectId) => apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks`),
  getCode: (projectId) => apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/code`),
  configureCode: (projectId, code) =>
    apiPut(`/api/projects/${encodeURIComponent(projectId)}/work/code`, { code }),
  listTopics: (projectId) => apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/topics`),
  configureTopicCode: (projectId, topicId, code) =>
    apiPut(`/api/projects/${encodeURIComponent(projectId)}/work/topics/${encodeURIComponent(topicId)}/code`, { code }),
  createTask: (projectId, payload) =>
    apiPost(`/api/projects/${encodeURIComponent(projectId)}/work/tasks`, payload),
  getTask: (projectId, taskId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}`),
  updateSource: (projectId, taskId, payload) =>
    apiPut(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/source`, payload),
  getGitOutcomes: (projectId, taskId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/git-outcomes`),
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
  uploadAttachment: (projectId, taskId, file) => {
    const form = new FormData()
    form.append('file', file)
    return apiPost(
      `/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/attachments`,
      form
    )
  },
  downloadAttachment: (projectId, taskId, attachmentId) =>
    apiGet(
      `/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/attachments/${encodeURIComponent(attachmentId)}/download`,
      {},
      true,
      'blob'
    ),
  removeAttachment: (projectId, taskId, attachmentId) =>
    apiRequest(
      `/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/attachments/${encodeURIComponent(attachmentId)}`,
      { method: 'DELETE' }
    ),
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
