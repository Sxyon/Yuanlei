# 图解与证据维护

当前图稿入口见<a href="index.html" target="_blank" rel="noopener">图解导航</a>。原7份图表示目标架构、历史候选页面关系或冻结任务依赖，当前实现以SYS/LOG源码证据为准。每目录的candidate.json拥有图稿定义，HTML由Archify生成，禁止直接改生成HTML。

当前图稿与校验回执的精确映射由`交付汇总.json`拥有，按candidate和HTML双指纹选择通过的回执；旧失败或旧字节回执仅供修复追溯。`review-2`、`review-3`是本轮工具修复证据，不是产品阶段。截图回执仍标为pending，因为图像采集不等于目视审阅；实际审阅范围和结论单独保存在LOG-MG-002。

图号与SYS/DEV对象号保持一致。修订先改Owner文档和candidate，再完整finalize，使用新证据目录重新捕获并核对。文档构建复制HTML和PNG/SVG相同字节；candidate和校验JSON保留仓库内，不进入静态站点图稿发布。

DB-G08为项目主题的渐进推进管理流程候选，candidate和失败finalize回执在08-progressive目录。校验未通过，暂无HTML交付，也未执行浏览器或目视验收。原DB-G02/03降为历史参考，不领取旧T任务；DB-G05待S07默认主题强化时参考。当前需求与任务以新版SYS-DB-001及DEV-DB-001为准。新增图稿未加入旧交付汇总的7图指纹，按本目录自身回执核对。

DB-G09在10-stage-relations-20261011维护，以architecture模式表达七段任务与验收关系，candidate、HTML与finalize回执独立保存。每段对应原要求，先交本段结果，验收通过后细化下一段；未通过返回本段，更早假设失效按DEV定位前段重审。09-stage-acceptance-20261011仅保存被拒绝的workflow试稿，不能混用其HTML或失败回执。DB-G09实际检查和目视范围见LOG-DB-001第11节。
