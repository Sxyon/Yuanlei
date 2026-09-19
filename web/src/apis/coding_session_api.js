import { apiGet, apiPost } from './base'

const CODING_SESSION_PATH = '/api/coding/sessions'

export const codingSessionApi = {
  list: (conversationId) => {
    const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ''
    return apiGet(`${CODING_SESSION_PATH}${query}`)
  },

  detail: (sessionId, afterSeq = 0, eventLimit = 100) =>
    apiGet(
      `${CODING_SESSION_PATH}/${encodeURIComponent(sessionId)}?after_seq=${afterSeq}&event_limit=${eventLimit}`
    ),

  terminalTicket: (sessionId) =>
    apiPost(`${CODING_SESSION_PATH}/${encodeURIComponent(sessionId)}/terminal-ticket`, {})
}
