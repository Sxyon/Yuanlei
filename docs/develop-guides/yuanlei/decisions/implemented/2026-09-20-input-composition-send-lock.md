# 输入法组合期发送锁

状态：implemented
类型：bug-fix
Owner：web/src/utils/sendLock.js

## 问题

中文、日文等输入法在 `compositionstart` 到 `compositionend` 期间使用 Enter 确认候选字。如果输入组件把这次 Enter 同时当作发送指令，消息会在文本尚未稳定时被提交。不同浏览器中 `compositionend` 和后续 keydown 的时序存在差异，只检查当前 composing 状态仍可能误发。

## 决策

由 `web/src/utils/sendLock.js` 统一拥有输入法组合期的短时发送禁止规则。`AgentInputArea.vue` 和 `MessageInputComponent.vue` 共用该规则：组合期内禁止 Enter 发送，`compositionend` 后的紧邻按键事件仍在有限窗口内被拦截。这是局部交互修复，不引入持久化状态或后端协议。

## 替代方案

- 每个输入组件各自维护时序逻辑：拒绝。同一浏览器边界会出现多份实现并逐渐分歧。
- 只读取 `KeyboardEvent.isComposing`：拒绝。该值无法覆盖部分浏览器在 `compositionend` 后的紧邻 keydown。
- 把锁提升为全局状态：拒绝。输入法组合期属于具体输入控件，全局状态会使无关输入框相互干扰。

## 后果

- 两个消息输入入口使用同一份发送判定，新的输入入口也需要复用该 Owner。
- 短时窗口是对浏览器事件时序的兼容约束；调整它需要以中文或日文输入的真实事件序列验证。
- 上游如果提供等价的统一规则且两个入口均接入，可删除该差异。

## 验证

- Inspected：`web/src/utils/sendLock.js` 拥有组合期与短时窗口判定，`AgentInputArea.vue` 和 `MessageInputComponent.vue` 均调用它。
- Not run：当前 `web/test/unit` 没有覆盖输入法事件序列的独立测试；后续修改时序或扩大输入入口前应先补该负向用例。
