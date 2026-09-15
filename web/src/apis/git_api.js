import { apiDelete, apiGet, apiPost, apiPut } from './base'

export const gitApi = {
  getConnections: () => apiGet('/api/git/connections'),
  createConnection: (payload) => apiPost('/api/git/connections', payload),
  updateCredential: (connectionId, apiToken) =>
    apiPut(`/api/git/connections/${connectionId}/credential`, { api_token: apiToken }),
  deleteConnection: (connectionId) => apiDelete(`/api/git/connections/${connectionId}`)
}
