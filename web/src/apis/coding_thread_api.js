import { apiGet, apiPost } from './base'

const CODING_THREAD_PATH = '/api/coding/threads'

export const codingThreadApi = {
  sandbox: (threadId) => apiGet(`${CODING_THREAD_PATH}/${encodeURIComponent(threadId)}/sandbox`),

  terminal: (threadId) =>
    apiPost(`${CODING_THREAD_PATH}/${encodeURIComponent(threadId)}/terminal`, {}),

}
