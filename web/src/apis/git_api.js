import { apiDelete, apiGet, apiPost, apiPut, buildQuery } from './base'

export const gitApi = {
  getConnections: () => apiGet('/api/git/connections'),
  getConnectionRepositories: (connectionId) => apiGet(`/api/git/connections/${connectionId}/repositories`),
  getConnectionBranches: (connectionId, owner, name) =>
    apiGet(`/api/git/connections/${connectionId}/branches?${buildQuery({ owner, name })}`),
  createConnection: (payload) => apiPost('/api/git/connections', payload),
  updateCredential: (connectionId, apiToken) =>
    apiPut(`/api/git/connections/${connectionId}/credential`, { api_token: apiToken }),
  deleteConnection: (connectionId) => apiDelete(`/api/git/connections/${connectionId}`)
}
