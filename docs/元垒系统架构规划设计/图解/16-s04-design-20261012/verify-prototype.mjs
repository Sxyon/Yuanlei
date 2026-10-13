import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { createHash } from 'node:crypto'
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const folder = path.dirname(fileURLToPath(import.meta.url)), source = path.join(folder, 'prototype.html')
const original = await readFile(source), sha = bytes => createHash('sha256').update(bytes).digest('hex')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const requests = [], errors = [], checks = []
page.on('request', r => { if (/^https?:/.test(r.url())) requests.push(r.url()) })
page.on('pageerror', e => errors.push(e.message))
const check = (v, title) => { assert.ok(v, title); checks.push(title) }
const go = async view => { await page.locator('#view').selectOption(view) }
const act = async action => {
 const target = page.locator(`[data-action="${action}"]`).first()
 if (await target.evaluate(el => el.closest('details') && !el.closest('details').open)) await page.locator('#content > details > summary').click()
 await target.click()
}
const text = async () => page.locator('#content').innerText()
const out = path.join(folder, 'browser'); await mkdir(out, { recursive: true })
try {
 await page.goto(pathToFileURL(source).href)
 check((await text()).includes('个人公共表示'), '个人公共使用边界明确')
 await page.screenshot({ path: path.join(out, 'catalog-light-1440.png'), fullPage: true })
 await page.locator('[data-scope="builtin"]').click(); await act('editor')
 check(await page.locator('#definition').getAttribute('readonly') !== null, '内置定义只读')
 check(await page.locator('[data-action="replace"], [data-action="disable"], [data-action="withdraw"]').count() === 0, '内置页不提供替换停用撤回')
 await act('copy'); check((await text()).includes('个人公共'), '复制建立独立个人来源入口')
 await page.locator('#name').fill('合成修改'); await act('save')
 check((await text()).includes('真实持久化未执行'), '候选保存演示不冒充真实')
 await act('disable'); check((await text()).includes('既有绑定继续加载'), '停用确认展示准确来源与影响')
 await act('confirm-operation'); await act('restore'); await act('confirm-operation')
 await act('withdraw'); check(await page.locator('#reason').count() === 1, '安全撤回提供原因输入')
 await act('confirm-operation'); check(await page.locator('#reason').count() === 1, '空原因不完成撤回')
 await page.locator('#reason').fill('合成审阅原因'); await act('confirm-operation')
 await act('restore'); check(await page.locator('#reason').count() === 1, '恢复撤回需原因并说明影响')
 await page.locator('#reason').fill('合成复核通过'); await act('confirm-operation')
 await act('preview'); check((await text()).includes('此处只演示入口，不保存选择'), '隔离预览边界明确')
 await act('publish'); check((await text()).includes('发布不会自动更新项目选择'), '发布与选择分开')
 await page.screenshot({ path: path.join(out, 'editor-light-1440.png'), fullPage: true })
 await act('versions'); check((await text()).includes('版本内容不可覆盖'), '不可变版本入口')
 await go('selection'); check((await text()).includes('类型与容量'), '文件映射归属路径类型容量边界')
 check((await text()).includes('绑定通过不表示业务已可用'), '选择未冒充真实业务可用')
 await page.screenshot({ path: path.join(out, 'selection-light-1440.png'), fullPage: true })
 await page.locator('#pick').selectOption('builtin-default-v1')
 check((await text()).includes('没有项目文件要求'), '默认版本无文件要求')
 check((await text()).includes('切换到 默认管理 1.0.0 · 内置'), '确认区显示准确目标版本来源')
 await page.locator('#pick').selectOption('builtin-research-v1')
 await page.locator('#path').fill('/reports/survey.json')
 await page.locator('#pick').selectOption('personal-reading-v1')
 check(await page.locator('#path').inputValue() === '', '切版本清空旧映射')
 check((await text()).includes('我的阅读主题 1.0.0 · 个人公共'), '确认区跟随个人来源')
 await page.locator('#pick').selectOption('builtin-research-v1')
 await act('choose'); check((await text()).includes('尚未绑定'), '缺少映射不完成演示选择')
 await act('normal'); await page.locator('#path').fill('/reports/survey.json')
 check((await page.locator('#mapping-summary').innerText()).includes('survey → /reports/survey.json'), '确认区即时显示文件映射变化')
 await act('choose'); check((await text()).includes('调研阅读 1.0.0'), '合成流程选择准确版本')
 check(!(await text()).includes('访谈样本=12'), '正式位置没有合成业务内容')
 await go('selection'); await page.locator('#project').selectOption('市场复核')
 check((await text()).includes('第 5 次修订'), '第二项目保持自己的演示绑定')
 check(!(await page.locator('#pick').innerText()).includes('访谈研究专属'), '专属来源不列入其他项目')
 await page.locator('#project').selectOption('访谈研究'); check((await text()).includes('第 3 次修订'), '第一项目绑定仍独立')
 for (const s of ['loading','empty','denied','invalid','conflict','missing','tampered','withdrawn','dbfail']) {
   await act(s); check((await page.locator('[role="alert"]').innerText()).length > 10, `状态 ${s} 有原因`); await act('normal')
 }
 await go('project'); await act('tampered'); check((await text()).includes('原绑定保留'), '坏包恢复保留原绑定')
 await page.screenshot({ path: path.join(out, 'tampered-light-1440.png'), fullPage: true })
 await go('maintenance'); check((await text()).includes('普通用户页面只提供检查说明'), '部署恢复没有网页数据库管理按钮')
 await act('clean'); check((await text()).includes('本稿未删除任何文件'), '维护稿无真实清理副作用')
 for (const width of [1440, 1024, 768, 375]) {
   await page.setViewportSize({ width, height: 1000 })
   for (const theme of ['light','dark']) {
     await page.locator('body').evaluate((el,t)=>el.classList.toggle('dark',t==='dark'),theme)
     for (const view of ['catalog','editor','selection','project','maintenance']) {
       await go(view)
       check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1), `${view} ${width} ${theme} 无整页溢出`)
     }
   }
 }
 await page.setViewportSize({width:375,height:1000}); await go('selection')
 await page.screenshot({path:path.join(out,'selection-dark-375.png'),fullPage:true})
 check(requests.length===0,'平台 HTTP 请求为零'); check(errors.length===0,'无浏览器脚本错误')
 check(sha(await readFile(source))===sha(original),'浏览器回执与冻结原型字节一致')
 await writeFile(path.join(out,'receipt.json'),JSON.stringify({kind:'isolated-design-only',sourceSha256:sha(original),checks,httpRequests:requests,scriptErrors:errors},null,2)+'\n')
 console.log(JSON.stringify({checks:checks.length,httpRequests:requests.length,scriptErrors:errors.length,sourceSha256:sha(original)}))
} finally { await browser.close() }
