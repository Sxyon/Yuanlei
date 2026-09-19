import { apiGet, apiPost } from './base'

const CODING_SANDBOX_PATH = '/api/coding/sandboxes'

export const codingSandboxApi = {
  list: () => apiGet(CODING_SANDBOX_PATH),

  provision: (agentSlug, projectId) =>
    apiPost(
      `${CODING_SANDBOX_PATH}/${encodeURIComponent(agentSlug)}/${encodeURIComponent(projectId)}/provision`,
      {}
    ),

  suspend: (agentSlug, projectId) =>
    apiPost(
      `${CODING_SANDBOX_PATH}/${encodeURIComponent(agentSlug)}/${encodeURIComponent(projectId)}/suspend`,
      {}
    ),

  rebuild: (agentSlug, projectId) =>
    apiPost(
      `${CODING_SANDBOX_PATH}/${encodeURIComponent(agentSlug)}/${encodeURIComponent(projectId)}/rebuild`,
      {}
    )
}
