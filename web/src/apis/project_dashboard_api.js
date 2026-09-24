import { apiGet } from './base'

export const projectDashboardApi = {
  /** 读取项目 Dashboard 页面状态、revision 与内容。 */
  getDashboard(projectId) {
    return apiGet(`/api/projects/${encodeURIComponent(projectId)}/dashboard`)
  }
}
