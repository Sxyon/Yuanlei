/**
 * 编码凭据表单的纯逻辑：模式判定、载荷构建、校验、供应商选项与状态文案。
 */

export const CREDENTIAL_MODE_OPTIONS = [
  { value: 'manual', label: '手动配置', description: '自行填写供应商、端点和模型' },
  { value: 'inherit', label: '引用·共用密钥', description: '渠道与模型跟随模型供应商，密钥共用' },
  { value: 'custom', label: '引用·单独密钥', description: '渠道与模型跟随供应商，密钥单独配置' }
]

export const UNAVAILABLE_REASON_LABELS = {
  provider_missing: '供应商已删除',
  provider_disabled: '供应商已停用',
  provider_key_missing: '供应商缺少密钥',
  model_not_enabled: '模型未启用',
  credential_key_missing: '单独密钥缺失'
}

export const createCredentialDraft = () => ({
  executor: 'opencode',
  mode: 'manual',
  provider: '',
  base_url: '',
  model: '',
  api_key: '',
  model_provider_id: ''
})

export const credentialModeOf = (row) => {
  if (row?.source !== 'model_provider') return 'manual'
  return row?.key_mode === 'custom' ? 'custom' : 'inherit'
}

export const credentialAvailabilityOf = (row) => {
  if (row?.source === 'model_provider' && row?.availability === 'unavailable') {
    return {
      available: false,
      label: UNAVAILABLE_REASON_LABELS[row.unavailable_reason] || '不可用',
      detail: row.unavailable_detail || ''
    }
  }
  return { available: true, label: '可用', detail: '' }
}

export const credentialSourceLabel = (row) => {
  if (credentialModeOf(row) === 'manual') return row?.provider || ''
  const base = row?.provider_display_name || row?.model_provider_id || ''
  return row?.model ? `${base} · ${row.model}` : base
}

export const validateCredentialDraft = (draft) => {
  if (!draft?.executor) return '请选择执行器'
  if (draft.mode === 'manual') {
    if (!String(draft.provider || '').trim()) return '请填写供应商标识'
    if (!String(draft.api_key || '').trim()) return '请填写 API Key'
    return ''
  }
  if (!String(draft.model_provider_id || '').trim()) return '请选择模型供应商'
  if (!String(draft.model || '').trim()) return '请选择模型'
  if (draft.mode === 'custom' && !String(draft.api_key || '').trim()) return '请填写单独密钥'
  return ''
}

export const buildCredentialPayload = (draft) => {
  if (draft.mode === 'manual') {
    return {
      executor: draft.executor,
      source: 'manual',
      provider: String(draft.provider || '').trim(),
      api_key: draft.api_key,
      base_url: String(draft.base_url || '').trim() || null,
      model: String(draft.model || '').trim() || null
    }
  }
  const payload = {
    executor: draft.executor,
    source: 'model_provider',
    model_provider_id: draft.model_provider_id,
    key_mode: draft.mode,
    model: draft.model
  }
  if (draft.mode === 'custom') payload.api_key = draft.api_key
  return payload
}

export const providerOptionsOf = (providers) =>
  (providers || []).map((provider) => ({
    value: provider.provider_id,
    label: provider.is_enabled ? provider.display_name : `${provider.display_name}（已停用）`
  }))

export const modelOptionsOf = (provider) =>
  (provider?.models || []).map((model) => ({
    value: model.id,
    label: model.display_name || model.id
  }))

export const findModelProvider = (providers, providerId) =>
  (providers || []).find((provider) => provider.provider_id === providerId) || null
