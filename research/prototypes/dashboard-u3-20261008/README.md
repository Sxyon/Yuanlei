# Dashboard U3 隔离原型

本目录拥有 U3 第一、二轮可操作原型及合成检查结果，不参与元垒应用构建。数据、工作、交付、意见与问题全部为合成；模拟办理只保存到这个原型的浏览器 sessionStorage。没有认证、数据库、Agent 或真实发布连接。

在仓库根启动：

```sh
python3 research/prototypes/dashboard-u3-20261008/make_samples.py
python3 research/prototypes/dashboard-u3-20261008/server.py
```

服务仅监听 `127.0.0.1:8767`。使用 HTTP 打开，浏览器直接打开文件不能加载模块。用 Ctrl+C 停止服务；顶部“重置合成状态”只清除原型 sessionStorage。浏览器关闭后的原型草稿不承诺长期保存。

- `index.html#a/alpha/overview`：A 主方案，管理、业务、正式工作和准确多结果详情。
- `index.html#b/alpha/queue`：B 高频跨项目办理切片，共用同一合成数据与状态。
- `index.html#c/alpha/business`：C 业务观察/全屏返回切片。
- `lab.html`：R1 有限数据、准确导航、负向输入与结构压力样例。

公平对照时每个方案开始前重置；不同方案共用状态，后操作的方案会看到前一方案的模拟办理结果。独立文件页仍能回准确结果；原意见按项目、工作、结果隔离。

主视觉原型使用原生浏览器界面代码，便于隔离验证交互；R1 技术样例使用仓库当前安装的 Vue 3.5.41 runtime-only 浏览器模块。server 只提供这一个明确的本地运行时路径，不提供任意仓库读取接口。该运行时不存在时 R1 返回明确缺失，视觉原型仍可运行；未引入或选择产品组件库。

`sample-data` 和 `resolve-navigation` 是仅用于合成试验的有界 GET 服务，拒绝跨项目绑定、对象错配和未知输入，没有产品认证含义。旧 `lab.html` 定义只消费四类可信素材；其空间压力目标图是明确标注的手绘参照，未被旧渲染器执行。第二轮 `spatial.html` 在独立入口比较有限坐标素材与编译 Vue，保留旧拒绝证据。

`check-prototype.cjs` 使用 Playwright 和独立浏览器上下文，输出 `evidence/checks.json` 与截图。使用已安装的 Playwright 时可直接执行；其他环境通过 `YUANLEI_U3_PLAYWRIGHT` 指定模块位置、`YUANLEI_U3_CHROME` 指定浏览器执行文件。没有自动安装或自动下载依赖。

```sh
node research/prototypes/dashboard-u3-20261008/check-prototype.cjs
```

PDF 文件用于阅读空间和独立打开示例，快速查看中明确标注分页模拟；未实现元垒的 PDF/Office 转换和历史证据存储。正式观察与未验范围由文档目录中的《信息架构与Dashboard-U3第一轮原型与观察-2026-10-08》拥有。

PDF 字节由 `make_samples.py` 重建，不依赖被仓库忽略的 PDF 文件进入版本控制。检查截图与 JSON 属于本轮原型研究证据；浏览器缓存与运行目录不作为交付。

第二轮连续任务入口为 `index.html?walk=1#a/alpha/overview`；任务说明的前后切换不记录完成，也不自动执行业务。观察请一次汇总误认、寻找、返回和阅读困难；脚本数据不能替代真实用户观察。

同一小空间对照入口为 `spatial.html`。先在仓库根用已有 Node 运行固定 SFC 的本地构建：

```sh
node research/prototypes/dashboard-u3-20261008/spatial/build.cjs
```

该构建读取当前 `web/node_modules` 的 Vue/编译器与 esbuild，没有新增安装；编译固定手写合成样例并输出被忽略的 `.build/`。缺包时页面 R2 明确失败、R1 保留。构建包含语法及未许可依赖的负向样例，其拒绝记录在 `evidence/spatial-build.json`。构建产物不进入提交，重新检出后需重建。服务在第二轮更新了有限读取端点，已运行旧进程时需停止并重新启动同一隔离服务。

第二轮检查为 `node research/prototypes/dashboard-u3-20261008/check-round2.cjs`（沿用 Playwright/Chrome 环境输入），输出 `evidence/round2-checks.json`。正式结论由《信息架构与Dashboard-U3连续任务与空间对照-2026-10-08》拥有；第一轮失败与拒绝证据保留，旧 `lab.html` 不被覆盖成扩展成功。

回归旧九组时设置 `YUANLEI_U3_EVIDENCE_DIR=research/prototypes/dashboard-u3-20261008/evidence/round2-regression`，保留第一轮截图和拒绝记录。检查记录使用 round 表示专项日期、executedAt 表示真实 UTC 执行时间。
