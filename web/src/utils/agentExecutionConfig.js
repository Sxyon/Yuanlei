/**
 * Agent 执行配置（sandbox / coding）的解析、规范化与差异构建。
 * 供 Agent 编辑与项目覆盖两处表单复用，保证提交载荷与后端校验语义一致。
 */

export const EXECUTOR_OPTIONS = [
  { value: 'opencode', label: 'OpenCode' },
  { value: 'codex', label: 'Codex' }
]

export const SANDBOX_MODE_OPTIONS = [
  { value: 'shared', label: '共享', description: '跟随会话线程，临时创建，不占用专属配额' },
  { value: 'dedicated', label: '专属', description: '按 Agent + 项目共享，支持恢复与常驻' }
]

export const SANDBOX_LIFECYCLE_OPTIONS = [
  { value: 'ephemeral', label: 'ephemeral', description: '随用随建，运行结束按空闲阈值回收' },
  { value: 'persistent', label: 'persistent', description: '空闲回收后保留记录，可按策略恢复' },
  { value: 'resident', label: 'resident', description: '常驻，不自动回收（占用常驻配额）' }
]

export const SANDBOX_RESUME_POLICY_OPTIONS = [
  { value: 'auto', label: 'auto', description: '回收后下次使用自动恢复' },
  { value: 'confirm', label: 'confirm', description: '回收后需显式重建才恢复' }
]

const EXECUTOR_VALUES = EXECUTOR_OPTIONS.map((option) => option.value)
const LIFECYCLE_VALUES = SANDBOX_LIFECYCLE_OPTIONS.map((option) => option.value)
const RESUME_POLICY_VALUES = SANDBOX_RESUME_POLICY_OPTIONS.map((option) => option.value)

export const defaultSandboxPolicy = () => ({
  mode: 'shared',
  lifecycle: 'ephemeral',
  resume_policy: 'auto',
  idle_suspend_seconds: null
})

export const defaultCodingSettings = () => ({
  executors: [],
  default_executor: null
})

const isPlainObject = (value) => !!value && typeof value === 'object' && !Array.isArray(value)

/**
 * 把任意配置块规范化为后端可接受的 sandbox 块；shared 固定为 ephemeral。
 */
export const normalizeSandboxPolicy = (sandbox) => {
  const raw = isPlainObject(sandbox) ? sandbox : {}
  const mode = raw.mode === 'dedicated' ? 'dedicated' : 'shared'
  const lifecycle =
    mode === 'shared'
      ? 'ephemeral'
      : LIFECYCLE_VALUES.includes(raw.lifecycle)
        ? raw.lifecycle
        : 'ephemeral'
  const resumePolicy = RESUME_POLICY_VALUES.includes(raw.resume_policy)
    ? raw.resume_policy
    : 'auto'
  const idleSeconds = Number.isInteger(raw.idle_suspend_seconds)
    ? Math.max(0, raw.idle_suspend_seconds)
    : null
  return {
    mode,
    lifecycle,
    resume_policy: resumePolicy,
    idle_suspend_seconds: idleSeconds
  }
}

/**
 * 把任意配置块规范化为后端可接受的 coding 块；未知执行器与失效默认值被丢弃。
 */
export const normalizeCodingSettings = (coding) => {
  const raw = isPlainObject(coding) ? coding : {}
  const requested = Array.isArray(raw.executors) ? raw.executors : []
  const executors = EXECUTOR_VALUES.filter((value) => requested.includes(value))
  const defaultExecutor = executors.includes(raw.default_executor) ? raw.default_executor : null
  return { executors, default_executor: defaultExecutor }
}

/**
 * 从 config_json / config_overrides 读取执行配置并补齐默认值。
 */
export const parseExecutionConfig = (config) => ({
  sandbox: normalizeSandboxPolicy(config?.sandbox),
  coding: normalizeCodingSettings(config?.coding)
})

/**
 * 生成只包含发生变化段的写入补丁；无变化时返回空对象。
 */
export const buildExecutionConfigPatch = ({ initial, current }) => {
  const initialSandbox = normalizeSandboxPolicy(initial?.sandbox)
  const currentSandbox = normalizeSandboxPolicy(current?.sandbox)
  const initialCoding = normalizeCodingSettings(initial?.coding)
  const currentCoding = normalizeCodingSettings(current?.coding)

  const patch = {}
  if (JSON.stringify(initialSandbox) !== JSON.stringify(currentSandbox)) {
    patch.sandbox = currentSandbox
  }
  if (JSON.stringify(initialCoding) !== JSON.stringify(currentCoding)) {
    patch.coding = currentCoding
  }
  return patch
}

/**
 * 深拷贝执行配置，用于建立初始基线。
 */
export const cloneExecutionConfig = (config) =>
  JSON.parse(
    JSON.stringify({
      sandbox: normalizeSandboxPolicy(config?.sandbox),
      coding: normalizeCodingSettings(config?.coding)
    })
  )
