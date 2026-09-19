<template>
  <div class="agent-execution-form" :class="{ 'is-readonly': disabled }">
    <section class="execution-section">
      <div class="section-heading">
        <span>沙盒生命周期</span>
        <a-button
          v-if="sandboxOverridden && !disabled"
          type="link"
          size="small"
          class="reset-section-btn"
          @click="emit('reset-sandbox')"
        >
          恢复继承
        </a-button>
      </div>

      <a-form layout="vertical">
        <a-form-item label="沙盒模式">
          <a-radio-group
            :value="sandbox.mode"
            :disabled="disabled"
            button-style="solid"
            @update:value="handleModeChange"
          >
            <a-radio-button v-for="option in SANDBOX_MODE_OPTIONS" :key="option.value" :value="option.value">
              {{ option.label }}
            </a-radio-button>
          </a-radio-group>
          <p class="field-hint">{{ modeHint }}</p>
        </a-form-item>

        <a-form-item label="生命周期">
          <a-select
            :value="sandbox.lifecycle"
            :disabled="disabled || sandbox.mode !== 'dedicated'"
            :options="lifecycleOptions"
            class="field-select"
            @update:value="(value) => updateSandbox({ lifecycle: value })"
          />
          <p class="field-hint">{{ lifecycleHint }}</p>
        </a-form-item>

        <a-form-item label="恢复策略">
          <a-select
            :value="sandbox.resume_policy"
            :disabled="disabled || sandbox.mode !== 'dedicated'"
            :options="resumePolicyOptions"
            class="field-select"
            @update:value="(value) => updateSandbox({ resume_policy: value })"
          />
          <p class="field-hint">{{ resumePolicyHint }}</p>
        </a-form-item>

        <a-form-item label="空闲回收秒数">
          <a-input-number
            :value="sandbox.idle_suspend_seconds"
            :min="0"
            :disabled="disabled || sandbox.mode !== 'dedicated'"
            placeholder="默认"
            class="field-number"
            @update:value="(value) => updateSandbox({ idle_suspend_seconds: Number.isInteger(value) ? value : null })"
          />
          <p class="field-hint">留空使用服务默认；resident 固定不自动回收，0 表示显式不回收。</p>
        </a-form-item>
      </a-form>
    </section>

    <section class="execution-section">
      <div class="section-heading">
        <span>编码执行器</span>
        <a-button
          v-if="codingOverridden && !disabled"
          type="link"
          size="small"
          class="reset-section-btn"
          @click="emit('reset-coding')"
        >
          恢复继承
        </a-button>
      </div>

      <a-form layout="vertical">
        <a-form-item label="执行器白名单">
          <a-checkbox-group
            :value="coding.executors"
            :options="EXECUTOR_OPTIONS"
            :disabled="disabled"
            @update:value="handleExecutorsChange"
          />
          <p class="field-hint">只有在此声明的执行器才允许被编码工具选择。</p>
        </a-form-item>

        <a-form-item label="默认执行器">
          <a-select
            :value="coding.default_executor ?? undefined"
            :options="defaultExecutorOptions"
            :disabled="disabled || !coding.executors.length"
            allow-clear
            placeholder="未设置"
            class="field-select"
            @update:value="(value) => updateCoding({ default_executor: value ?? null })"
          />
          <p class="field-hint">默认执行器必须属于白名单；未设置时由工具调用显式指定。</p>
        </a-form-item>
      </a-form>

      <p class="credential-hint">
        执行器需要先在「设置 → 编码凭据」中为该用户配置凭据，否则编码工具会提示未启用。
      </p>
    </section>

    <section v-if="showWarmUp" class="execution-section">
      <div class="section-heading">
        <span>沙盒预热</span>
      </div>
      <p class="field-hint">
        按保存后的策略创建或恢复专属沙盒；已有 runtime 会被复用，Workdir 文件不受影响。
      </p>
      <a-button
        type="primary"
        :loading="warmUpLoading"
        :disabled="disabled || warmUpDisabled"
        @click="emit('warm-up')"
      >
        立即预热
      </a-button>
      <p v-if="warmUpDisabled" class="field-hint">当前不是专属模式，保存为「专属」后可用。</p>
    </section>
  </div>
</template>

<script setup>
import { computed } from 'vue'

import {
  EXECUTOR_OPTIONS,
  SANDBOX_LIFECYCLE_OPTIONS,
  SANDBOX_MODE_OPTIONS,
  SANDBOX_RESUME_POLICY_OPTIONS
} from '@/utils/agentExecutionConfig'

const props = defineProps({
  /** 当前沙盒策略（含默认值）。 */
  sandbox: { type: Object, required: true },
  /** 当前编码执行器设置（含默认值）。 */
  coding: { type: Object, required: true },
  /** 只读展示（无管理权限时）。 */
  disabled: { type: Boolean, default: false },
  /** 是否存在沙盒项目覆盖。 */
  sandboxOverridden: { type: Boolean, default: false },
  /** 是否存在编码项目覆盖。 */
  codingOverridden: { type: Boolean, default: false },
  /** 是否展示预热入口（项目上下文）。 */
  showWarmUp: { type: Boolean, default: false },
  warmUpLoading: { type: Boolean, default: false },
  /** 当前配置不允许预热时禁用按钮。 */
  warmUpDisabled: { type: Boolean, default: false }
})

const emit = defineEmits(['update:sandbox', 'update:coding', 'reset-sandbox', 'reset-coding', 'warm-up'])

const modeHint = computed(
  () => SANDBOX_MODE_OPTIONS.find((option) => option.value === props.sandbox.mode)?.description || ''
)

const lifecycleOptions = computed(() =>
  SANDBOX_LIFECYCLE_OPTIONS.map((option) => ({ value: option.value, label: option.label }))
)

const lifecycleHint = computed(
  () => SANDBOX_LIFECYCLE_OPTIONS.find((option) => option.value === props.sandbox.lifecycle)?.description || ''
)

const resumePolicyOptions = computed(() =>
  SANDBOX_RESUME_POLICY_OPTIONS.map((option) => ({ value: option.value, label: option.label }))
)

const resumePolicyHint = computed(
  () =>
    SANDBOX_RESUME_POLICY_OPTIONS.find((option) => option.value === props.sandbox.resume_policy)?.description || ''
)

const defaultExecutorOptions = computed(() =>
  EXECUTOR_OPTIONS.filter((option) => props.coding.executors.includes(option.value))
)

const updateSandbox = (patch) => emit('update:sandbox', { ...props.sandbox, ...patch })

const updateCoding = (patch) => emit('update:coding', { ...props.coding, ...patch })

const handleModeChange = (mode) => {
  updateSandbox(mode === 'shared' ? { mode, lifecycle: 'ephemeral' } : { mode })
}

const handleExecutorsChange = (executors) => {
  const defaultExecutor = executors.includes(props.coding.default_executor)
    ? props.coding.default_executor
    : null
  updateCoding({ executors, default_executor: defaultExecutor })
}
</script>

<style scoped>
.agent-execution-form {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.execution-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-bottom: 18px;
  border-bottom: 1px solid var(--gray-150);
}

.execution-section:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
  color: var(--gray-900);
  font-size: 14px;
  font-weight: 600;
}

.reset-section-btn {
  padding: 0;
  height: auto;
  font-size: 12px;
}

.field-select,
.field-number {
  width: 100%;
  max-width: 320px;
}

.field-hint {
  margin: 4px 0 0;
  color: var(--gray-500);
  font-size: 12px;
  line-height: 1.5;
}

.credential-hint {
  margin: 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--gray-10);
  color: var(--gray-600);
  font-size: 12px;
  line-height: 1.5;
}

.is-readonly {
  opacity: 0.85;
}
</style>
