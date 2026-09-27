import { apiGet, apiPost } from './base'

/** 独立项目工作任务。 */
export const projectWorkApi = {
  getTask: (projectId, taskId) =>
    apiGet(`/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}`),
  addComment: (projectId, taskId, content) =>
    apiPost(
      `/api/projects/${encodeURIComponent(projectId)}/work/tasks/${encodeURIComponent(taskId)}/comments`,
      { content }
    )
}
