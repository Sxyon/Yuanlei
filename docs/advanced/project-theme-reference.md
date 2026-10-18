# 项目主题配置参考

本页面向需要直接编辑主题 JSON 或准备主题 ZIP 的用户和主题维护者。操作步骤见[制作和使用项目主题](../intro/project-theme-authoring.md)。当前协议以`formatVersion: 1`为准；不支持的字段、成员、组件或 ABI 会明确拒绝，不会静默忽略或自动转换。

## 包结构

主题包是一个 ZIP，只接受以下成员：

| 成员 | 要求 |
| --- | --- |
| `manifest.json` | 必需；主题清单、文件 alias、包内素材和兼容声明 |
| `theme.json` | 必需；主题名称、版本、显示选项和页面定义 |
| `assets/...` | 可选；每个包内素材必须在`manifest.assets`中声明，路径以`assets/`开头 |

不能包含未声明成员、目录、符号链接、加密成员、绝对路径、反斜杠、冒号或`..`路径段。压缩方式只接受存储或 deflate。不能把项目文件、项目路径、业务数据、凭据或宿主路径打进包；项目文件通过 alias 在目标项目重新绑定。

## manifest 字段

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `formatVersion` | 整数 | 是 | 当前只能为`1` |
| `componentAbi` | 整数 | 是 | 组件能力版本，只能为`1`、`2`或`3`；能力页至少为2，呈现／隐藏导航至少为3 |
| `theme` | 字符串 | 是 | 固定为`"theme.json"` |
| `source` | 字符串 | 是 | 作者声明，只用于展示来源说明；不代表登录身份、来源归属或权限 |
| `files` | 对象 | 是 | 项目文件 alias → `application/json`或`image/png`；文件本身不进入 ZIP |
| `assets` | 对象 | 是 | 包内素材 alias → `{ "path", "mediaType", "sha256" }`；成员必须真实存在于 ZIP |

`files`和`assets`的 alias 合计最多64项，每个 alias 最长160字符，不能包含 NUL。建议使用字母、数字、下划线或短横线，不要使用路径分隔符。

### 包内素材声明

```json
{
  "assets": {
    "logo": {
      "path": "assets/logo.png",
      "mediaType": "image/png",
      "sha256": "<64位小写十六进制摘要>"
    }
  }
}
```

`assets/logo.png`必须作为 ZIP 成员存在，实际字节的 SHA-256 必须与`sha256`一致。摘要可以从已发布版本的「包成员」面板读取，或用系统工具计算，例如：

```bash
sha256sum assets/logo.png
# macOS
shasum -a 256 assets/logo.png
```

`mediaType`只接受`application/json`和`image/png`；JSON 必须是有效 JSON，PNG 必须可安全解码且不是动画。

## theme 字段

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `id` | 字符串 | 无 | 作者定义的主题标识，不是来源 ID、版本 ID 或权限凭据；复制主题时通常保持不变 |
| `version` | 字符串 | 无 | 发布标识，最长160字符；内容变化时必须使用新值 |
| `name` | 字符串 | 无 | 主题显示名；来源名称在建立／导入时单独设置 |
| `topicLabel` | 字符串 | 无 | 业务名词的界面显示，例如“议题”“课题”“战略规划”；不改变业务对象、状态和权限 |
| `baseVersion` | 整数或空 | 空 | 基础界面版本；声明能力页或呈现配置时必须为`1` |
| `density` | 字符串 | `comfortable` | `comfortable`或`compact` |
| `accent` | 字符串 | `teal` | `teal`、`blue`或`slate` |
| `presentation` | 字符串 | `baseline` | `baseline`、`focus`或`research`；非`baseline`需要`componentAbi: 3`且`baseVersion: 1` |
| `hiddenCapabilities` | 字符串数组 | `[]` | 隐藏导航项；不能重复、不能包含`overview`；需要`componentAbi: 3`且`baseVersion: 1` |
| `pages` | 数组 | 无 | 至少1页、最多32页；页面顺序即导航顺序 |

`hiddenCapabilities`只改变导航呈现，不取消后端权限。准确的对象链接仍可打开，页面仍按业务权限读取；隐藏不是授权边界。

## 页面

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | 字符串 | 页面唯一标识；同主题内不能重复 |
| `title` | 字符串 | 导航和页面标题 |
| `description` | 字符串 | 页面说明，不能为空 |
| `layout` | 字符串 | `overview`、`reading`或`full` |
| `capability` | 字符串或空 | 九项平台能力之一；为空表示展示页 |
| `blocks` | 数组 | 展示页的区块；能力页必须为空 |

`capability`只接受：`overview`、`blueprints`、`topics`、`plans`、`work`、`inspection`、`files`、`agents`、`settings`。同一能力只能出现一次。

- **能力页**使用平台可信业务界面，不能放自定义区块；页面标题可以改，业务内容、状态和权限仍由原业务模块拥有。
- **展示页**的`capability`为空，至少包含一个区块；所有内容来自业务只读投影、项目文件 alias 或包内素材。
- 没有声明的能力会继承基础界面；`overview`不能被隐藏。隐藏其他能力不会删除对应页面或权限。

## 区块类型与绑定

所有区块都有`id`（同一页面内唯一）、`title`、`region`（`summary`、`main`或`aside`）和可选`action`。`action`只能跳转到本主题已定义的页面：

```json
{ "kind": "page", "pageId": "topics" }
```

| 类型 | 作用 | 绑定 | 可选项 |
| --- | --- | --- | --- |
| `summary` | 项目摘要或目标说明 | `{ "kind": "business", "resource": "project" }` | `variant`: `counts`或`description` |
| `records` | 业务对象集合 | `{ "kind": "business", "resource": "topics"｜"decisions"｜"workTasks", "scope": "project"｜"selectedTopic" }` | `variant`: `list`、`table`、`selector`、`compactSelector`、`conclusions`、`attention`、`history`；`statuses`可选 |
| `topic` | 当前选定议题的问题和预期产出 | `{ "kind": "business", "resource": "selectedTopic" }` | 无 |
| `discussion` | 当前选定议题的只读讨论 | `{ "kind": "business", "resource": "discussions" }` | 无 |
| `json` | JSON 资料 | `{ "kind": "file"｜"asset", "alias": "..." }` | alias 必须声明且类型为`application/json` |
| `image` | PNG 资料 | `{ "kind": "file"｜"asset", "alias": "..." }` | alias 必须声明且类型为`image/png`；必须填写`alt` |

`records`还有这些约束：

- `table`、`selector`、`compactSelector`只能绑定`topics`。
- `conclusions`、`history`只能绑定`decisions`。
- `attention`只能绑定`workTasks`。
- 绑定`topics`时`scope`必须是`project`。
- `statuses`是可选的状态过滤；使用平台已有的业务状态，不确定时留空。填错只会得到空列表，不会改变业务状态。

区块不能携带 HTML、CSS、脚本、组件名、URL、SQL 或任意字段。未声明的字段会被整体拒绝。

## 兼容组合

| 想使用的功能 | 最低`componentAbi` | `baseVersion` | 其他限制 |
| --- | --- | --- | --- |
| 展示页、摘要／集合／议题／讨论／JSON／PNG区块 | 1 | 空 | 不能声明能力页、`presentation`或隐藏导航 |
| 九项能力页 | 2 | 必须为1 | 同一能力只能一页；能力页不能有区块 |
| 非`baseline`呈现、`hiddenCapabilities` | 3 | 必须为1 | 不能隐藏`overview`，不能重复 |
| 项目文件 alias、包内素材 | 1 | 视页面而定 | alias 必须声明，JSON／PNG 类型必须匹配 |

`componentAbi`高于3、`formatVersion`不是1、`baseVersion`不是1、未知字段或未知组件都会被拒绝。旧 ABI 版本继续按原能力加载；新配置不能假装被旧宿主理解。

## 项目文件与包内素材

| 对比 | 项目文件 alias | 包内素材 |
| --- | --- | --- |
| 声明位置 | `manifest.files` | `manifest.assets` |
| 是否在 ZIP 中 | 否 | 是，必须作为声明成员存在 |
| 谁拥有内容 | 目标项目 Workdir | 主题包作者 |
| 目标项目操作 | 预览／分配时填写项目内相对路径 | 不需要映射 |
| 适用 | 每个项目不同的数据、图片 | 主题自带、共用的图标或示例素材 |
| 缺失后果 | 明确“未绑定”；未满足不能应用 | 包校验失败；不能发布 |

项目文件路径只存在于目标项目的选择记录，不进入主题包。预览使用临时映射，不写入项目选择；分配时才保存映射。共用 Workdir 的项目仍各自维护自己的选择和映射。

## 准备完整 ZIP

只改 JSON 定义时，直接在主题管理编辑器保存并校验即可。要新增或替换包内素材：

1. 从准确已发布版本「导出原包」，得到原始 ZIP。
2. 解压到普通目录，保留`manifest.json`、`theme.json`和`assets/`结构。
3. 修改 JSON，添加或替换`assets/`中的 JSON／PNG，并更新`manifest.assets`的`path`、`mediaType`、`sha256`。
4. 重新压缩为 ZIP，确保`manifest.json`和`theme.json`在包根目录，且没有未声明成员。
5. 在主题管理「替换草稿 ZIP」上传完整包，再保存校验。

示例（在解压目录内执行）：

```bash
# 计算摘要后填入 manifest.assets
sha256sum assets/logo.png

# 只打包声明成员；不要带入 .DS_Store、备份文件或项目资料
zip -r ../my-theme.zip manifest.json theme.json assets
```

上传后系统会重新解析实际字节并核对摘要；浏览器中的预检摘要不能替代服务端校验。

## 配额与限制

| 项目 | 上限 |
| --- | --- |
| 单个 ZIP | 8 MiB |
| 实际展开内容 | 32 MiB |
| ZIP 成员数 | 128 |
| 单成员／单个项目文件 | 8 MiB |
| 页面数 | 32 |
| 每页区块数 | 64 |
| 文件与素材 alias 合计 | 64 |
| alias／来源名称／版本标识 | 160 字符 |
| PNG 解码像素合计 | 1600 万 |
| 项目文件绑定合计 | 32 MiB／1600 万像素 |
| 支持的内容类型 | `application/json`、`image/png` |
| 支持的压缩 | stored、deflate；不支持加密 |

主题显示名可以长于160字符，但作为默认目标来源名称时会被截断；建议控制在160字符以内。`theme.version`超过160字符不能发布。

## 校验错误与处理

| 提示类别 | 常见原因 | 处理 |
| --- | --- | --- |
| JSON 编码／重复字段 | 多写了逗号、重复键、非有限数值 | 修正 JSON 语法和重复键 |
| 定义不符合契约 | 未知字段、字段类型错误、取值不在允许列表 | 对照本页字段表修正；不要添加自定义字段 |
| 页面／区块重复 | 页面 ID 或同页区块 ID 重复 | 改成唯一 ID |
| 能力重复／页面内容冲突 | 同一能力多页，或能力页同时放区块 | 每个能力只保留一个能力页，区块移到展示页 |
| 页面引用不存在 | `action.pageId`指向未定义页面 | 改成已定义页面 ID |
| alias 未声明／MIME 不匹配 | `json`区块绑定了非 JSON alias，或`image`区块绑定非 PNG alias | 在`manifest.files`／`assets`声明正确类型并保持 alias 一致 |
| 资源路径／摘要错误 | 素材不在`assets/`、路径含`..`、摘要不匹配或成员缺失 | 使用声明路径的普通成员，更新实际 SHA-256 |
| 资源类型／PNG 错误 | 声明 JSON 实际不是 JSON，或 PNG 损坏／动画 | 提供有效 JSON／PNG |
| ABI／基础版本不兼容 | 能力页用了 ABI1，或呈现配置缺少基础界面 | 按[兼容组合](#兼容组合)提升能力或从较新版本复制 |
| 版本冲突 | 同来源同版本已发布不同字节 | 修改`theme.version`后重新保存发布 |
| 候选冲突 | 另一窗口已推进草稿修订 | 重新读取目录，保留输入后重新确认 |
| 文件未绑定／文件错误 | 目标项目没有映射、文件不存在、类型不符或超出边界 | 在预览／分配弹窗填写项目内普通文件路径，按 alias 类型提供 JSON／PNG |
| 来源停用／撤回 | 来源状态不允许新发布或加载 | 停用可恢复；撤回需维护者填写原因后恢复 |
| 包缺失／损坏 | 主题文件域缺少原 ZIP 或摘要不匹配 | 用「存储检查与维护」核对；从可信备份恢复或明确选择其他版本 |

服务端会重新授权来源、项目和准确版本，并重新解析实际字节。前端的预检、按钮禁用和提示只改善体验，不是授权边界。

## 安全边界

- 主题包是数据，不是可执行程序；不能携带任意 Vue／HTML／JS／CSS、URL、SQL、凭据或宿主路径。
- 包内作者写入的文字、JSON 和 PNG 会随包携带，导出不承诺自动脱敏；导出前用「包成员」核对。
- `theme.id`、`manifest.source`和包摘要只代表作者声明与字节，不授予来源或项目权限。
- 项目业务数据、Project ID、Workdir 路径、文件映射、选择 generation、临时预览 query 和会话草稿不进入包。
- 导入只保存草稿；发布只生成不可变版本；分配才改变项目选择。三者不能互相代替。
- 主题维护、备份和恢复的部署边界见[维护和恢复项目主题文件](./project-theme-storage.md)。
