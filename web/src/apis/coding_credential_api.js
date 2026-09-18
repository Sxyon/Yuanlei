import { apiDelete, apiGet, apiPut } from './base'

const CODING_CREDENTIAL_PATH = '/api/user/coding-credentials'

export const codingCredentialApi = {
  list: () => apiGet(CODING_CREDENTIAL_PATH),

  save: (payload) => apiPut(CODING_CREDENTIAL_PATH, payload),

  remove: (executor, provider) =>
    apiDelete(
      `${CODING_CREDENTIAL_PATH}?executor=${encodeURIComponent(executor)}&provider=${encodeURIComponent(provider)}`
    )
}
