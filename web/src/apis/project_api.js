import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from './base'

export const projectApi = {
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

  deactivateRepository: (projectId, repositoryId) =>
    apiDelete(`/api/projects/${projectId}/repositories/${repositoryId}`),

  getGitWorktrees: (projectId) => apiGet(`/api/projects/${projectId}/git-worktrees`),

  cleanupGitWorktree: (projectId, worktreeId) =>
    apiDelete(`/api/projects/${projectId}/git-worktrees/${worktreeId}`),

  getHistoryCandidates: ({ query = '', limit = 20, offset = 0 } = {}) =>
    apiGet(`/api/projects/history-candidates?${buildQuery({ q: query, limit, offset })}`)
}
