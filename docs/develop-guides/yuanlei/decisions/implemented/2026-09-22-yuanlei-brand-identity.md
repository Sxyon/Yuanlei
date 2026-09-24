# 元垒品牌图形与文档站视觉身份

状态：implemented
类型：feature
Owner：docs/public/favicon.svg

## 问题

元垒把产品定义为个人与企业的 AI 中枢、总裁办与 CEO 办公室，文档站却仍交付 Yuxi 的黄色眼镜脸、Yuxi 字标和外部 Yuxi Open Graph 图片。站点主题还装配 `YuxiHome.vue`，新增的元垒首页没有成为实际入口；文字元数据即使改为 Yuanlei，浏览器标签、首屏、分享卡片和主题色仍表达上游品牌。

## 决策

元垒使用独立的“中心枢纽 + 四向垒块”图形。四个向心构件表达参谋决策、督查汇报、执行协同与知识底座围绕同一中枢工作；方正、互锁和逐层构筑的几何关系对应“垒”。主色使用电光青 `#28D7E5`、协同蓝 `#4C7DFF` 和深海靛 `#111831`，不使用上游黄色。

`docs/public/favicon.svg` 拥有小尺寸母标，ICO 从同一母标派生；Web 应用的 favicon 使用相同图形。深浅背景 lockup 复用相同母标并只改变字标前景色。部署、知识、Agent 编排和运行边界四枚文档入口图标使用同一垒块形态和色系，替代上游黄色吉祥物。1200×630 Open Graph 图片及 SVG 版本存放在文档静态资源中，站点元数据引用元垒站点自己的稳定地址。`docs/.vitepress/theme/index.ts` 装配 `YuanleiHome.vue`，首页可访问文本、动态场景和 VitePress 全局主题色使用同一元垒身份。

上游产品截图和供应商图标继续由原资源地址交付；它们解释当前能力，不拥有元垒品牌。

## 替代方案

- 只把黄色改成其他颜色：拒绝。眼镜脸和 Yuxi 字标仍然拥有上游识别语义，不能表达元垒的新身份。
- 使用复杂的写实城墙或盾牌：拒绝。小尺寸不可读，也容易落入安全产品的通用图形。
- 继续引用外部 Yuxi OG 图片：拒绝。分享卡片会继续传播旧品牌，而且元垒仓库不能拥有该资源的内容与发布生命周期。

## 后果

favicon、lockup、首页中枢、文档入口图标和分享卡片现在共享同一几何语言，文档站的浅色与深色主题共享青蓝/靛色系。SVG 字标使用系统中文无衬线字体栈，不同平台的字面宽度会有轻微差异；固定画布、字号和预留宽度避免裁切。社交平台可能缓存旧分享卡片，新文件名和 URL 使发布后的重新抓取不依赖覆盖原 Yuxi 资源。

与上游同步时保留元垒静态资产、`YuanleiHome.vue` 装配和主题色；上游首页功能改进可以迁移进元垒组件，但不能恢复 Yuxi 字标或黄色品牌语义。

## 验证

- `xmllint --noout` 验证文档与 Web favicon、两份 lockup、四枚入口图标及 OG SVG：Passed。
- Pillow 回读 OG 为 1200×630 RGB，已知黄色像素为 0；回读 ICO 包含 16、32、48、64 像素帧；字节对比确认文档与 Web favicon 相同：Passed。
- `pnpm run build` 构建文档站，并回读生成的 HTML 已引用新的元垒 OG 地址：Passed。
- 在本地 VitePress 预览中检查浅色和深色首页、字标、动态中枢、四枚入口图标、移动端排版、主题切换和可访问文本：Passed。
- Web 应用 `pnpm run lint:check`、`pnpm run test:unit`（379 passed）与 `pnpm run build`：Passed。
- `python3 scripts/verify_engineering_contracts.py` 与 `python3 -m unittest scripts.test_verify_engineering_contracts`（70 passed）：Passed。
- `docker compose exec api uv run --group test pytest test/unit -m "not slow"`：Not run；Compose 因本地 `.env` 缺少必填密钥而无法启动。
- 公开 OG URL 当前返回 HTTP 404：Not verified；部署工作流只发布 `main`，合并至 `develop-v0.0.1` 不会使分享图上线。
- `git diff --check`：Passed。
