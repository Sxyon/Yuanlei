import { apiGet, apiPost, apiPut } from './base'

const projectPath = (projectId) => `/api/projects/${encodeURIComponent(projectId)}`

export const governanceBoardApi = {
  /** 读取单个 Project 的督查板只读视图。 */
  getProjectBoard(projectId) {
    return apiGet(`/api/projects/${encodeURIComponent(projectId)}/governance/board`)
  },

  /** 跨项目读取当前用户可见的督查板只读视图。 */
  getCrossProjectBoard() {
    return apiGet('/api/governance/board')
  },

  listBlueprints(projectId) {
    return apiGet(`${projectPath(projectId)}/blueprint`)
  },

  getBlueprint(projectId, name) {
    return apiGet(`${projectPath(projectId)}/blueprint/${encodeURIComponent(name)}`)
  },

  putBlueprint(projectId, name, content) {
    return apiPut(`${projectPath(projectId)}/blueprint/${encodeURIComponent(name)}`, { content })
  },

  createTopic(projectId, payload) {
    return apiPost(`${projectPath(projectId)}/governance/topics`, {
      ...payload,
      source_channel: 'project'
    })
  },

  reviewTopic(projectId, topicId, approve) {
    return apiPost(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/review`,
      { approve }
    )
  },

  createDecision(projectId, payload) {
    return apiPost(`${projectPath(projectId)}/governance/decisions`, payload)
  },

  createTask(projectId, payload) {
    return apiPost(`${projectPath(projectId)}/governance/tasks`, payload)
  },

  reviewTask(projectId, taskId, approve) {
    return apiPost(
      `${projectPath(projectId)}/governance/tasks/${encodeURIComponent(taskId)}/review`,
      { approve }
    )
  },

  listDelegations(projectId) {
    return apiGet(`${projectPath(projectId)}/delegations`)
  },

  delegateTask(projectId, taskId, executorKey) {
    return apiPost(
      `${projectPath(projectId)}/governance/tasks/${encodeURIComponent(taskId)}/delegations`,
      {
        executor_key: executorKey
      }
    )
  },

  getDelegation(projectId, operationId) {
    return apiGet(`${projectPath(projectId)}/delegations/${encodeURIComponent(operationId)}`)
  },

  collectDelegation(projectId, operationId) {
    return apiPost(
      `${projectPath(projectId)}/delegations/${encodeURIComponent(operationId)}/collect`,
      {}
    )
  }
}
