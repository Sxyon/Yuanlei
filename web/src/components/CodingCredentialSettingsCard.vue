<template>
  <div class="coding-credential-settings">
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">编码执行器凭据</div>
        <p class="section-description">
          配置 opencode / codex 执行编码任务所需的模型渠道与密钥：可手动配置，也可引用「模型供应商」已启用的渠道与密钥。凭据加密存储、保存后不再回显，仅对之后创建的专属沙盒生效。
        </p>
      </div>
      <div class="header-actions">
        <a-button
          class="refresh-btn lucide-icon-btn"
          :loading="loading"
          title="刷新"
          @click="loadAll"
        >
          <template #icon><RefreshCw :size="16" :class="{ spin: loading }" /></template>
        </a-button>
      </div>
    </div>

    <div class="env-tip">
      <Info :size="14" class="tip-icon" />
      <span>codex 需要支持 Responses API 的端点；opencode 使用 OpenAI 兼容端点。</span>
    </div>

    <a-spin :spinning="loading">
      <div v-if="credentials.length" class="credential-list">
        <div v-for="item in credentials" :key="item.id" class="credential-item">
          <div class="credential-meta">
            <span class="credential-executor">{{ item.executor }}</span>
            <span class="credential-source">{{ credentialSourceLabel(item) }}</span>
            <a-tag :color="item.source === 'model_provider' ? 'blue' : 'default'">
              {{ modeLabelOf(item) }}
            </a-tag>
            <a-tooltip :title="unavailableTooltip(item)">
              <a-tag :color="credentialAvailabilityOf(item).available ? 'success' : 'error'">
                {{ credentialAvailabilityOf(item).label }}
              </a-tag>
            </a-tooltip>
            <span class="credential-model" v-if="item.source === 'manual'">
              {{ item.has_key ? '已配置密钥' : '缺少密钥' }}
            </span>
          </div>
          <a-button danger size="small" @click="removeCredential(item)">删除</a-button>
        </div>
      </div>
      <a-empty v-else :image="simpleImage" description="尚未配置编码执行器凭据" />
    </a-spin>

    <div class="credential-form">
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :span="6">
            <a-form-item label="执行器">
              <a-select v-model:value="draft.executor">
                <a-select-option value="opencode">opencode</a-select-option>
                <a-select-option value="codex">codex</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
          <a-col :span="18">
            <a-form-item label="配置模式">
              <a-radio-group v-model:value="draft.mode" button-style="solid">
                <a-radio-button v-for="option in CREDENTIAL_MODE_OPTIONS" :key="option.value" :value="option.value">
                  {{ option.label }}
                </a-radio-button>
              </a-radio-group>
              <p class="field-hint">{{ modeDescription }}</p>
            </a-form-item>
          </a-col>
        </a-row>

        <template v-if="draft.mode === 'manual'">
          <a-row :gutter="16">
            <a-col :span="8">
              <a-form-item label="供应商标识">
                <a-input v-model:value="draft.provider" placeholder="例如 sf / deepseek / openai" />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="模型">
                <a-input v-model:value="draft.model" placeholder="例如 deepseek-ai/DeepSeek-V4-Flash" />
              </a-form-item>
            </a-col>
            <a-col :span="8">
              <a-form-item label="服务端点（base URL）">
                <a-input v-model:value="draft.base_url" placeholder="例如 https://api.siliconflow.cn/v1" />
              </a-form-item>
            </a-col>
          </a-row>
        </template>

        <template v-else>
          <a-row :gutter="16">
            <a-col :span="12">
              <a-form-item label="模型供应商">
                <a-select
                  v-model:value="draft.model_provider_id"
                  :options="providerOptions"
                  placeholder="选择已配置的模型供应商"
                  show-search
                  option-filter-prop="label"
                />
              </a-form-item>
            </a-col>
            <a-col :span="12">
              <a-form-item label="模型">
                <a-select
                  v-model:value="draft.model"
                  :options="modelOptions"
                  :disabled="!draft.model_provider_id"
                  placeholder="选择供应商已启用的 chat 模型"
                />
              </a-form-item>
            </a-col>
          </a-row>
          <p class="field-hint" v-if="selectedProvider">
            渠道与模型跟随供应商「{{ selectedProvider.display_name }}」；{{ draft.mode === 'inherit' ? '密钥共用供应商配置，供应商轮换密钥后自动生效。' : '密钥单独保存在此处，渠道仍跟随供应商。' }}
          </p>
          <p class="field-hint" v-if="draft.executor === 'codex'">
            注意：codex 需要该供应商端点支持 Responses API，否则运行时会失败。
          </p>
        </template>

        <a-form-item v-if="draft.mode !== 'inherit'" label="API Key">
          <a-input-password
            v-model:value="draft.api_key"
            :placeholder="draft.mode === 'custom' ? '单独密钥，仅保存时提交' : '仅保存时提交，之后不再显示'"
            autocomplete="new-password"
          />
        </a-form-item>

        <a-alert v-if="draftError" type="warning" :message="draftError" show-icon class="draft-alert" />

        <div class="form-actions">
          <a-button type="primary" :loading="saving" :disabled="!!draftError" @click="saveCredential">
            保存凭据
          </a-button>
        </div>
      </a-form>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Empty, message } from 'ant-design-vue'
import { Info, RefreshCw } from '@lucide/vue'
import { codingCredentialApi } from '@/apis/coding_credential_api'
import {
  CREDENTIAL_MODE_OPTIONS,
  buildCredentialPayload,
  createCredentialDraft,
  credentialAvailabilityOf,
  credentialModeOf,
  credentialSourceLabel,
  findModelProvider,
  modelOptionsOf,
  providerOptionsOf,
  validateCredentialDraft
} from '@/utils/codingCredentialForm'

const MODE_LABELS = {
  manual: '手动',
  inherit: '共用密钥',
  custom: '单独密钥'
}

const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE
const loading = ref(false)
const saving = ref(false)
const credentials = ref([])
const providers = ref([])
const draft = reactive(createCredentialDraft())

const providerOptions = computed(() => providerOptionsOf(providers.value))
const selectedProvider = computed(() =>
  findModelProvider(providers.value, draft.model_provider_id)
)
const modelOptions = computed(() => modelOptionsOf(selectedProvider.value))
const draftError = computed(() => validateCredentialDraft(draft))
const modeDescription = computed(
  () => CREDENTIAL_MODE_OPTIONS.find((option) => option.value === draft.mode)?.description || ''
)

const modeLabelOf = (row) => MODE_LABELS[credentialModeOf(row)] || '手动'

const unavailableTooltip = (row) => {
  const state = credentialAvailabilityOf(row)
  return state.detail || state.label
}

const loadCredentials = async () => {
  const data = await codingCredentialApi.list()
  credentials.value = Array.isArray(data) ? data : []
}

const loadProviders = async () => {
  const data = await codingCredentialApi.providers()
  providers.value = Array.isArray(data) ? data : []
}

const loadAll = async () => {
  loading.value = true
  try {
    await loadCredentials()
  } catch (error) {
    message.error(error?.message || '加载编码凭据失败')
  }
  try {
    await loadProviders()
  } catch (error) {
    message.error(error?.message || '加载模型供应商失败')
  } finally {
    loading.value = false
  }
}

const saveCredential = async () => {
  if (draftError.value) {
    message.warning(draftError.value)
    return
  }
  saving.value = true
  try {
    await codingCredentialApi.save(buildCredentialPayload(draft))
    draft.api_key = ''
    message.success('编码凭据已保存')
    await loadCredentials()
  } catch (error) {
    message.error(error?.message || '保存编码凭据失败')
  } finally {
    saving.value = false
  }
}

const removeCredential = async (item) => {
  try {
    await codingCredentialApi.remove(item.executor, item.provider)
    message.success('编码凭据已删除')
    await loadCredentials()
  } catch (error) {
    message.error(error?.message || '删除编码凭据失败')
  }
}

watch(
  () => draft.model_provider_id,
  () => {
    if (!modelOptions.value.some((option) => option.value === draft.model)) {
      draft.model = modelOptions.value[0]?.value || ''
    }
  }
)

watch(
  () => draft.mode,
  (mode) => {
    if (mode === 'inherit') draft.api_key = ''
    if (mode === 'manual') draft.model_provider_id = ''
  }
)

onMounted(loadAll)
</script>

<style scoped>
.coding-credential-settings {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.header-section {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary, #1f2329);
}

.section-description {
  margin: 4px 0 0;
  color: var(--text-secondary, #646a73);
  font-size: 13px;
}

.env-tip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--fill-quaternary, #f5f6f7);
  color: var(--text-secondary, #646a73);
  font-size: 13px;
}

.credential-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.credential-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--border-primary, #dee0e3);
  border-radius: 6px;
}

.credential-meta {
  display: flex;
  gap: 12px;
  align-items: center;
  font-size: 13px;
}

.credential-executor {
  font-weight: 600;
}

.credential-source {
  color: var(--text-primary, #1f2329);
}

.credential-model,
.credential-key {
  color: var(--text-secondary, #646a73);
}

.field-hint {
  margin: 4px 0 0;
  color: var(--text-secondary, #646a73);
  font-size: 12px;
  line-height: 1.5;
}

.credential-form {
  border-top: 1px solid var(--border-primary, #dee0e3);
  padding-top: 16px;
}

.draft-alert {
  margin-bottom: 12px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}

.spin {
  animation: coding-credential-spin 1s linear infinite;
}

@keyframes coding-credential-spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
