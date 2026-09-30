import { apiGet, apiRequest } from './base'

/** 当前用户收件箱。 */
export const inboxApi = {
  list: (folder, before = null) =>
    apiGet(`/api/inbox?folder=${encodeURIComponent(folder)}${before ? `&before=${encodeURIComponent(before)}` : ''}`),
  update: (itemId, payload) =>
    apiRequest(`/api/inbox/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload)
    })
}
