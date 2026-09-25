import { apiGet } from './base'

export const governanceBoardApi = {
  /** 读取单个 Project 的督查板只读视图。 */
  getProjectBoard(projectId) {
    return apiGet(`/api/projects/${encodeURIComponent(projectId)}/governance/board`)
  },

  /** 跨项目读取当前用户可见的督查板只读视图。 */
  getCrossProjectBoard() {
    return apiGet('/api/governance/board')
  }
}
