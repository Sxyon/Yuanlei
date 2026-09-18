import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from './base'

/**
 * 项目数字员工 API
 * 项目私有智能体的归属、覆盖配置与解绑。
 * 权限要求: 项目 owner（所有登录用户）
 */
export const projectAgentApi = {
  list: (projectId) => apiGet(`/api/projects/${projectId}/agents`),

  create: (projectId, payload) => apiPost(`/api/projects/${projectId}/agents`, payload),

  bind: (projectId, agentSlug) =>
    apiPost(`/api/projects/${projectId}/agents/bind`, { agent_slug: agentSlug }),

  updateOverrides: (projectId, agentSlug, configJson, resetFields = []) =>
    apiPut(`/api/projects/${projectId}/agents/${agentSlug}`, {
      config_json: configJson,
      reset_fields: resetFields
    }),

  unbind: (projectId, agentSlug, { deleteAgent = false } = {}) =>
    apiDelete(
      `/api/projects/${projectId}/agents/${agentSlug}?${buildQuery({ delete_agent: deleteAgent })}`
    )
}
