import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from './base'

export const projectApi = {
  getSettings: (projectId) => apiGet(`/api/projects/${projectId}/settings`),

  saveSettings: (projectId, payload) => apiPut(`/api/projects/${projectId}/settings`, payload),

  saveKnowledgeLinks: (projectId, kbIds) =>
    apiPut(`/api/projects/${projectId}/knowledge-links`, { kb_ids: kbIds }),

  getProjects: () => apiGet('/api/projects'),

  createProject: ({ requestId, name, mode, path = null }) =>
    apiPost('/api/projects', {
      request_id: requestId,
      name,
      workdir: {
        mode,
        ...(mode === 'linked' && path ? { path: String(path).replace(/^\/+/, '') } : {})
      }
    }),

  renameProject: (projectId, name) => apiPut(`/api/projects/${projectId}`, { name }),

  deleteProject: (projectId) => apiDelete(`/api/projects/${projectId}`),

  getRepositories: (projectId) => apiGet(`/api/projects/${projectId}/repositories`),

  createRepository: (projectId, payload) =>
    apiPost(`/api/projects/${projectId}/repositories`, payload),

  retryRepository: (projectId, repositoryId) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/retry`, {}),

  updateRepositoryPolicy: (projectId, repositoryId, payload) =>
    apiPut(`/api/projects/${projectId}/repositories/${repositoryId}/policy`, payload),

  getRepositoryBranches: (projectId, repositoryId) =>
    apiGet(`/api/projects/${projectId}/repositories/${repositoryId}/branches`),

  configureGitResource: (projectId, repositoryId, payload) =>
    apiPut(`/api/projects/${projectId}/repositories/${repositoryId}/resource`, payload),

  checkoutGitResource: (projectId, repositoryId) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/checkout`, {}),

  reviewGitResource: (projectId, repositoryId) =>
    apiGet(`/api/projects/${projectId}/repositories/${repositoryId}/review`),

  commitGitResource: (projectId, repositoryId, payload) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/commit`, payload),

  discardGitResource: (projectId, repositoryId, payload) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/discard`, payload),
  pushGitResource: (projectId, repositoryId, payload) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/push`, payload),

  getGitOccupancies: (projectId) => apiGet(`/api/projects/${projectId}/git-occupancies`),

  releaseGitResource: (projectId, repositoryId, scopeKey) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/release`, { scope_key: scopeKey }),

  getGitPullRequests: (projectId, repositoryId) =>
    apiGet(`/api/projects/${projectId}/repositories/${repositoryId}/pull-requests`),

  createGitPullRequest: (projectId, repositoryId, payload) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/pull-requests`, payload),

  mergeGitPullRequest: (projectId, repositoryId, number, payload) =>
    apiPost(`/api/projects/${projectId}/repositories/${repositoryId}/pull-requests/${number}/merge`, payload),

  deactivateRepository: (projectId, repositoryId) =>
    apiDelete(`/api/projects/${projectId}/repositories/${repositoryId}`),

  getGitWorktrees: (projectId) => apiGet(`/api/projects/${projectId}/git-worktrees`),

  cleanupGitWorktree: (projectId, worktreeId) =>
    apiDelete(`/api/projects/${projectId}/git-worktrees/${worktreeId}`),

  getHistoryCandidates: ({ query = '', limit = 20, offset = 0 } = {}) =>
    apiGet(`/api/projects/history-candidates?${buildQuery({ q: query, limit, offset })}`)
}
