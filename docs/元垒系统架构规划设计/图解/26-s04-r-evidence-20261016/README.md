# DB-S04-R 隔离实施证据

本目录仅保存合成项目的实际执行证据，不是新规划。需求、实施约束和实际结果分别归原SYS15、DEV12.2及LOG51。A1原稿与平台增补保持原目录。

- `browser-proof.json`：正常平台入口及项目快捷入口的可见DOM、URL、准确版本、generation和故障协议摘录。
- `binding-final.json`、`binding-restart.json`：分别在API重启前后，通过真实HTTP、PG绑定联结版本行、ZIP字节摘要回读；A默认13、B默认4、C未绑定0。
- `default-baseline.jpg`、`default-settings-baseline.jpg`：产品修改前默认基线；`default-restored.jpg`：最终恢复默认。
- `platform-research.jpg`、`platform-no-settings.jpg`：平台分配调研及无settings声明主题后原地回读。
- `platform-fault.jpg`、`saved-load-failed.jpg`、`emergency-fallback.jpg`、`permission-loss.jpg`、`dual-entry-conflict.jpg`：坏包、写后网络故障、应急、失权和双入口冲突。

## 复现环境

从仓库Compose创建独立数据库`yuanlei_s04_repair_evidence`，不要覆盖日常数据库。隔离脚本固定该库及独立文件根，不接受任意项目作为故障目标。若同名环境已存在，复核其归属后复用；不要通过删除日常卷重建。

```bash
docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" yuanlei_s04_repair_evidence'
docker compose run --no-deps -d --name yuanlei-s04-repair -p 127.0.0.1:15064:5060 api python /app/test/e2e/project_theme_switch_app.py
docker exec yuanlei-s04-repair python /app/test/e2e/project_theme_switch_evidence.py prepare
VITE_API_URL=http://127.0.0.1:15064 pnpm --dir web exec vite --host 127.0.0.1 --port 15174 --strictPort
```

随机合成身份仅留容器私有`/tmp/s04-repair/session.json`，不输出或提交凭据。用该身份登录隔离站点，从首页→项目列表→A卡片／主题管理开始。完整步骤及版本账在LOG51；版本行路径从个人来源“S04-R无设置声明”→发布版本→分配到项目开始。

```bash
docker exec yuanlei-s04-repair python /app/test/e2e/project_theme_switch_evidence.py read
# 以下仅用于该具名隔离包，成对恢复
docker exec yuanlei-s04-repair python /app/test/e2e/project_theme_switch_evidence.py corrupt
docker exec yuanlei-s04-repair python /app/test/e2e/project_theme_switch_evidence.py restore
# 以下只切换隔离A的可见性，成对恢复
docker exec yuanlei-s04-repair python /app/test/e2e/project_theme_switch_evidence.py deny
docker exec yuanlei-s04-repair python /app/test/e2e/project_theme_switch_evidence.py allow
```

浏览器故障在响应阶段放行已成功PUT再拒绝GET，或拒绝PUT响应后放行核实GET；仅影响隔离API的Fetch资源，结束清空拦截。重新聚焦使用真实focus监听的受控事件，未声称操作系统级自动切窗。预览只用合成数据。主切换均用UI操作；旧书签测试单独打开陈旧展示URL，不算分配入口证明。

## 可拒绝的宿主证据

`web/test/unit/platformPageCache.test.js`编译当前真实AppLayout模板，断言同路由换版本generation会卸载旧页面并清理其局部输入。去掉非缓存component的scope key后，卸载数从1变0，测试失败；恢复后通过。`projectThemeHostSwitch.test.js`加载实际ProjectLayout及编辑登记，去掉同代state守卫或真实能力路由后，分别因草稿消失、仍停展示路由失败。Selection协议测试另证未知结果、409、加载失败、迟到返回与预检期间切目标。最终补齐平台focus回读：保留本次意图且使旧条件失效，保存前发出的旧回读不能覆盖成功；连续focus／visibility共享同一草稿确认。移除读epoch或确认Promise后分别因旧0覆盖新1、确认框2个而应1个失败，恢复后共17项通过。

本目录截图不证明调研内容组织或双数据已完成。未逐一浏览器穷举全部业务表单，详见LOG51的未验边界。
