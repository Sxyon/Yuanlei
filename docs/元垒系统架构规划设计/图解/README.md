# 图解与证据维护

当前图稿入口见<a href="index.html" target="_blank" rel="noopener">图解导航</a>。7份图表示目标架构、候选页面关系或冻结任务依赖，当前实现以SYS/LOG源码证据为准。每目录的candidate.json拥有图稿定义，HTML由Archify生成，禁止直接改生成HTML。

当前图稿与校验回执的精确映射由`交付汇总.json`拥有，按candidate和HTML双指纹选择通过的回执；旧失败或旧字节回执仅供修复追溯。`review-2`、`review-3`是本轮工具修复证据，不是产品阶段。截图回执仍标为pending，因为图像采集不等于目视审阅；实际审阅范围和结论单独保存在LOG-MG-002。

图号与SYS/DEV对象号保持一致。修订先改Owner文档和candidate，再完整finalize，使用新证据目录重新捕获并核对。文档构建复制HTML和PNG/SVG相同字节；candidate和校验JSON保留仓库内，不进入静态站点图稿发布。
