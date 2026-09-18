<template>
  <div class="coding-credential-settings">
    <div class="header-section">
      <div class="header-content">
        <div class="section-title">编码执行器凭据</div>
        <p class="section-description">
          配置 opencode / codex 执行编码任务所需的模型密钥。凭据加密存储、保存后不再回显，仅对之后创建的专属沙盒生效。
        </p>
      </div>
      <div class="header-actions">
        <a-button
          class="refresh-btn lucide-icon-btn"
          :loading="loading"
          title="刷新"
          @click="loadCredentials"
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
            <span class="credential-provider">{{ item.provider }}</span>
            <span class="credential-model">{{ item.model || '默认模型' }}</span>
            <span class="credential-key">{{ item.has_key ? '已配置密钥' : '缺少密钥' }}</span>
          </div>
          <a-button danger size="small" @click="removeCredential(item)">删除</a-button>
        </div>
      </div>
      <a-empty v-else :image="simpleImage" description="尚未配置编码执行器凭据" />
    </a-spin>

    <div class="credential-form">
      <a-form layout="vertical">
        <a-row :gutter="16">
          <a-col :span="8">
            <a-form-item label="执行器">
              <a-select v-model:value="draft.executor">
                <a-select-option value="opencode">opencode</a-select-option>
                <a-select-option value="codex">codex</a-select-option>
              </a-select>
            </a-form-item>
          </a-col>
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
        </a-row>
        <a-form-item label="服务端点（base URL）">
          <a-input v-model:value="draft.base_url" placeholder="例如 https://api.siliconflow.cn/v1" />
        </a-form-item>
        <a-form-item label="API Key">
          <a-input-password
            v-model:value="draft.api_key"
            placeholder="仅保存时提交，之后不再显示"
            autocomplete="new-password"
          />
        </a-form-item>
        <div class="form-actions">
          <a-button type="primary" :loading="saving" :disabled="!canSave" @click="saveCredential">
            保存凭据
          </a-button>
        </div>
      </a-form>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { message } from 'ant-design-vue'
import { Empty } from 'ant-design-vue'
import { Info, RefreshCw } from '@lucide/vue'
import { codingCredentialApi } from '@/apis/coding_credential_api'

const simpleImage = Empty.PRESENTED_IMAGE_SIMPLE
const loading = ref(false)
const saving = ref(false)
const credentials = ref([])
const draft = reactive({
  executor: 'opencode',
  provider: '',
  model: '',
  base_url: '',
  api_key: ''
})

const canSave = computed(
  () => Boolean(draft.provider.trim()) && Boolean(draft.api_key.trim()) && !saving.value
)

const loadCredentials = async () => {
  loading.value = true
  try {
    const data = await codingCredentialApi.list()
    credentials.value = Array.isArray(data) ? data : []
  } catch (error) {
    message.error(error?.message || '加载编码凭据失败')
  } finally {
    loading.value = false
  }
}

const saveCredential = async () => {
  saving.value = true
  try {
    await codingCredentialApi.save({
      executor: draft.executor,
      provider: draft.provider.trim(),
      model: draft.model.trim() || null,
      base_url: draft.base_url.trim() || null,
      api_key: draft.api_key
    })
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

onMounted(loadCredentials)
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

.credential-key {
  color: var(--text-secondary, #646a73);
}

.credential-form {
  border-top: 1px solid var(--border-primary, #dee0e3);
  padding-top: 16px;
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
