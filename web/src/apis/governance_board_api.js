import { apiGet, apiPost, apiPut, apiDelete } from './base'

const projectPath = (projectId) => `/api/projects/${encodeURIComponent(projectId)}`

export const governanceBoardApi = {
  /** 读取单个 Project 的督查板只读视图。 */
  getProjectBoard(projectId) {
    return apiGet(`/api/projects/${encodeURIComponent(projectId)}/governance/board`)
  },

  /** 读取与概览卡片同范围的分页列表。 */
  getOverviewPage(projectId, section, offset = 0, limit = 20) {
    return apiGet(
      `${projectPath(projectId)}/governance/overview?section=${encodeURIComponent(section)}&offset=${offset}&limit=${limit}`
    )
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

  createBlueprint(projectId, name, content) {
    return apiPost(`${projectPath(projectId)}/blueprint`, { name, content })
  },

  /** 修改当前蓝图名称，保留正文。 */
  renameBlueprint(projectId, name, newName) {
    return apiPost(`${projectPath(projectId)}/blueprint/${encodeURIComponent(name)}/rename`, {
      name: newName
    })
  },

  /** 永久删除当前蓝图。 */
  deleteBlueprint(projectId, name) {
    return apiDelete(`${projectPath(projectId)}/blueprint/${encodeURIComponent(name)}`)
  },

  /** 永久删除归档蓝图。 */
  deleteBlueprintArchive(projectId, name) {
    return apiDelete(`${projectPath(projectId)}/blueprint/history/${encodeURIComponent(name)}`)
  },

  listBlueprintArchives(projectId) {
    return apiGet(`${projectPath(projectId)}/blueprint/history`)
  },

  getBlueprintArchive(projectId, archiveName) {
    return apiGet(`${projectPath(projectId)}/blueprint/history/${encodeURIComponent(archiveName)}`)
  },

  archiveBlueprint(projectId, name) {
    return apiPost(`${projectPath(projectId)}/blueprint/${encodeURIComponent(name)}/archive`, {})
  },

  putBlueprint(projectId, name, content) {
    return apiPut(`${projectPath(projectId)}/blueprint/${encodeURIComponent(name)}`, { content })
  },

  listDecisions(projectId) {
    return apiGet(`${projectPath(projectId)}/governance/decisions`)
  },

  createTopic(projectId, payload) {
    return apiPost(`${projectPath(projectId)}/governance/topics`, {
      ...payload,
      source_channel: 'project'
    })
  },

  listTopics(projectId, includeArchived = false) {
    return apiGet(`${projectPath(projectId)}/governance/topics?include_archived=${includeArchived}`)
  },

  getTopicTimeline(projectId, topicId, before = null) {
    const query = before ? `?before=${before}` : ''
    return apiGet(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/timeline${query}`
    )
  },

  operateTopic(projectId, topicId, payload) {
    return apiPost(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/operations`,
      payload
    )
  },

  updateTopic(projectId, topicId, payload) {
    return apiPut(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}`,
      payload
    )
  },

  listTopicComments(projectId, topicId) {
    return apiGet(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/comments`
    )
  },

  createTopicComment(projectId, topicId, content, discussionType = 'discussion', options = {}) {
    return apiPost(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/comments`,
      { content, discussion_type: discussionType, ...options }
    )
  },

  getTopicDiscussion(projectId, topicId, commentId) {
    return apiGet(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/comments/${encodeURIComponent(commentId)}`
    )
  },

  getTopicFollowup(projectId, topicId) {
    return apiGet(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/followup`
    )
  },

  recordTopicDisposition(projectId, topicId, commentId, payload) {
    return apiPost(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/comments/${encodeURIComponent(commentId)}/dispositions`,
      payload
    )
  },

  recordTopicConfirmation(projectId, topicId, payload) {
    return apiPost(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/confirmations`,
      payload
    )
  },

  getTopicRevision(projectId, topicId, revision) {
    return apiGet(
      `${projectPath(projectId)}/governance/topics/${encodeURIComponent(topicId)}/revisions/${revision}`
    )
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

  getDecisionRevision(projectId, decisionId, revision) {
    return apiGet(
      `${projectPath(projectId)}/governance/decisions/${encodeURIComponent(decisionId)}/revisions/${revision}`
    )
  },

  getDecision(projectId, decisionId, before) {
    return apiGet(
      `${projectPath(projectId)}/governance/decisions/${encodeURIComponent(decisionId)}${before ? `?before=${before}` : ''}`
    )
  },

  updateDecision(projectId, decisionId, payload) {
    return apiPut(
      `${projectPath(projectId)}/governance/decisions/${encodeURIComponent(decisionId)}`,
      payload
    )
  },

  operateDecision(projectId, decisionId, payload) {
    return apiPost(
      `${projectPath(projectId)}/governance/decisions/${encodeURIComponent(decisionId)}/operations`,
      payload
    )
  },

  createDecisionErratum(projectId, decisionId, payload) {
    return apiPost(
      `${projectPath(projectId)}/governance/decisions/${encodeURIComponent(decisionId)}/errata`,
      payload
    )
  },

  createTask(projectId, payload) {
    return apiPost(`${projectPath(projectId)}/governance/tasks`, payload)
  },

  admitTask(projectId, taskId, payload) {
    return apiPost(
      `${projectPath(projectId)}/governance/tasks/${encodeURIComponent(taskId)}/admit`,
      payload
    )
  },

  reviewTask(projectId, taskId, approve) {
    return apiPost(
      `${projectPath(projectId)}/governance/tasks/${encodeURIComponent(taskId)}/review`,
      { approve }
    )
  },

  createDelegation(projectId, payload) {
    return apiPost(`${projectPath(projectId)}/delegations`, payload)
  },

  listDelegations(projectId) {
    return apiGet(`${projectPath(projectId)}/delegations`)
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
