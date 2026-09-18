/**
 * 项目智能体复制草稿：只构造前端编辑状态，不触发任何创建请求。
 */

export const DEFAULT_PROJECT_AGENT_NAME = '新建智能体'

export const buildCopiedProjectAgentDraft = (source, form = {}) => ({
  backend_id: source?.backend_id || form.backend_id || '',
  description: source?.description || '',
  icon: source?.icon || '',
  name:
    !form.name || form.name === DEFAULT_PROJECT_AGENT_NAME
      ? `${source?.name || '智能体'} 副本`
      : form.name,
  configValues: { ...((source?.context || {})) }
})
