/* global process */
import assert from 'node:assert/strict'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import path from 'node:path'

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE || 'playwright')
const fixture = JSON.parse(await readFile(process.env.THEME_EVIDENCE_SESSION, 'utf8'))
const root = process.cwd(), out = path.resolve(process.env.THEME_EVIDENCE_OUTPUT)
const api = process.env.THEME_EVIDENCE_API || 'http://127.0.0.1:15060'
const web = process.env.THEME_EVIDENCE_WEB || 'http://localhost:5173'
const files = ['web/src/components/project/ProjectThemeManager.vue', 'web/src/components/project/ProjectThemeSelection.vue', 'web/src/components/project/ProjectThemePanel.vue', 'web/src/apis/project_theme_api.js', 'backend/package/yuxi/services/project_theme_service.py', 'backend/package/yuxi/themes/packages.py']
const hashes = async () => Object.fromEntries(await Promise.all(files.map(async file => [file, createHash('sha256').update(await readFile(path.join(root, file))).digest('hex')])))
const frozen = await hashes(), checks = [], requests = [], errors = []
let stage = 'startup', delayResponse
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
await mkdir(out, { recursive: true })
const check = (value, title) => { assert.ok(value, title); checks.push(title) }
page.on('pageerror', error => errors.push(error.message))
await page.addInitScript(token => localStorage.setItem('user_token', token), fixture.users[0].token)
// 所有平台请求转发到隔离真实HTTP，响应字节原样返回，不stub账号／项目／主题。
await page.route('**/api/**', async route => {
 const request = route.request(), url = new URL(request.url())
 let response
 try { response = await page.request.fetch(api + url.pathname + url.search, { method: request.method(), headers: request.headers(), data: request.postDataBuffer() || undefined }) }
 catch { await route.abort('failed'); throw new Error(`隔离HTTP连接失败：${url.pathname}`) }
 requests.push({ path: url.pathname, method: request.method(), status: response.status() })
 if (delayResponse?.matches(url.pathname)) { delayResponse.seen(); await delayResponse.release }
 await route.fulfill({ response })
})
const button = name => page.getByRole('button', { name, exact: true })
try {
 let ready = false
 for (let i=0;i<60;i++) {
  try { const response = await page.request.get(`${api}/api/theme-sources`,{headers:{Authorization:`Bearer ${fixture.users[0].token}`}}); if(response.ok()){ready=true;break} } catch { /* 启动后仅以真实有权目录回读确认可访问。 */ }
  await new Promise(resolve=>setTimeout(resolve,500))
 }
 check(ready,'隔离服务有权目录实际可读')
 stage='catalog'
 await page.goto(`${web}/projects?tab=themes`)
 await page.getByText('来源目录', { exact: true }).waitFor()
 await page.getByText('平台内置', { exact: true }).click()
 const builtin = page.locator('.source').first()
 await builtin.waitFor(); await builtin.click()
 await page.locator('.version').first().waitFor()
 check(await button('安全撤回').count() === 0, '内置来源无维护权限入口')
 await page.screenshot({ path: path.join(out, 'builtin-light-1440.png'), fullPage: true })
 await page.locator('.version').first().getByRole('button', { name: '复制为个人来源', exact: true }).click()
 await page.getByLabel('候选JSON定义').waitFor()
 check((await page.getByLabel('候选JSON定义').inputValue()).includes('manifest'), '从真实原ZIP复制候选')
 const definition = JSON.parse(await page.getByLabel('候选JSON定义').inputValue())
 definition.theme.version = `s04-browser-${Date.now()}`
 definition.theme.name = '浏览器维护的阅读主题'
 await page.getByLabel('候选JSON定义').fill(JSON.stringify(definition, null, 2))
 check(await button('发布已保存候选').isDisabled() && await button('隔离预览').isDisabled(), '未保存编辑不能预览或发布旧候选')
 check(!requests.some(r=>r.path.endsWith('/publish')), '未保存编辑没有发发布请求')
 await button('保存并校验候选').click()
 await page.getByText('候选已保存并校验，旧发布版本与项目选择保留。', { exact: true }).waitFor()
 check(true, '真实候选编辑及校验完成')
 await button('隔离预览').click()
 await page.locator('.theme-host').waitFor()
 check((await page.locator('.preview-notice').innerText()).includes('业务及项目文件内容为合成预览'), '真实包与合成业务预览分开标识')
 await button('返回维护 / 选择').click()
 stage='publish'
 await button('发布已保存候选').click()
 await page.locator('.ant-popconfirm-buttons button').last().click()
 await page.locator('.version').first().waitFor()
 check((await page.locator('.version').first().innerText()).includes(definition.theme.version), '发布准确不可变版本')
 await page.screenshot({ path: path.join(out, 'published-light-1440.png'), fullPage: true })
 // 持有真实旧候选HTTP结果，切来源后释放，验证旧DTO不回填。
 let notifySeen, releaseOld
 const seen = new Promise(resolve=>{notifySeen=resolve}), release = new Promise(resolve=>{releaseOld=resolve})
 delayResponse = {matches: pathname=>pathname.endsWith('/candidate'),seen:notifySeen,release}
 await page.locator('.source[aria-current]').click(); await seen
 await page.getByText('平台内置', {exact:true}).click(); await page.locator('.source').first().click()
 releaseOld(); delayResponse=undefined
 await page.locator('.version').first().waitFor()
 check(await page.getByLabel('候选JSON定义').count()===0,'迟到真实候选响应不能污染已切换内置来源')
 check(await button('复制为个人来源').first().isEnabled(),'来源切换后旧请求不会遗留busy状态')
 await page.getByText('个人公共', {exact:true}).click(); await page.locator('.source').last().click()
 await page.getByLabel('候选JSON定义').waitFor(); await button('发布版本').click()
 stage='selection'
 await button('为项目选择').first().click()
 const projectSelect = page.getByLabel('主题目标项目')
 await projectSelect.click(); await page.getByText(fixture.projects[0].name, { exact: true }).last().click()
 const versionSelect = page.getByLabel('主题发布版本')
 await versionSelect.click(); await page.getByText(new RegExp(definition.theme.version)).last().click()
 await page.waitForFunction(() => !document.querySelector('.theme-select button.ant-btn-primary')?.disabled)
 stage='project'
 await button('保存项目选择').click()
 await page.locator('.project-theme-panel .theme-host').waitFor()
 check((await page.locator('.project-theme-panel').innerText()).includes('真实业务数据待 S05 接通'), '正式页不显示合成业务')
 check(!(await page.locator('.project-theme-panel').innerText()).includes('批准开展限定范围试点'), '合成决定未进入正式页面')
 await page.reload(); await page.locator('.project-theme-panel .theme-host').waitFor()
 check((await page.locator('.theme-status').innerText()).includes(definition.theme.version), '页面重新读取准确持久版本')
 await page.screenshot({ path: path.join(out, 'selected-light-1440.png'), fullPage: true })
 for (const width of [1024, 768, 375]) {
  await page.setViewportSize({width,height:1000})
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1), `正式主题 ${width}px 无整页溢出`)
 }
 await page.screenshot({ path: path.join(out, 'selected-light-375.png'), fullPage: true })
 // 第二个共目录项目选择调研版本：文件映射真实校验，内容仍待S05；PNG由真实版本读取。
 stage='research-resource'
 const headers = {Authorization:`Bearer ${fixture.users[0].token}`}
 const directory = await (await page.request.get(`${api}/api/theme-sources?project_id=${fixture.projects[1].id}`,{headers})).json()
 const research = directory.sources.find(source=>source.kind==='builtin' && source.versions[0].size>10000)
 const before = await (await page.request.get(`${api}/api/projects/${fixture.projects[1].id}/theme`,{headers})).json()
 const chosen = await page.request.put(`${api}/api/projects/${fixture.projects[1].id}/theme`,{headers,data:{version_id:research.versions[0].id,expected_generation:before.generation,files:{survey:'/data.json'}}})
 check(chosen.ok(),'第二个共目录项目真实选择及文件绑定通过')
 await page.setViewportSize({width:1440,height:1000})
 await page.goto(`${web}/projects/${fixture.projects[1].id}/dashboard?view=theme`)
 await page.locator('.project-theme-panel .theme-host').waitFor()
 await button('证据资料').click()
 await page.locator('.theme-host img').waitFor()
 check(await page.locator('.theme-host img').evaluate(img=>img.complete && img.naturalWidth>0),'包内PNG真实读取并浏览器解码')
 check((await page.locator('.theme-host').innerText()).includes('项目文件内容待 S05 接通'),'项目文件内容没有提前接入或合成')
 await page.screenshot({path:path.join(out,'resource-light-1440.png'),fullPage:true})
 await page.setViewportSize({width:375,height:1000})
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'真实包资源375px无整页溢出')
 await page.screenshot({path:path.join(out,'resource-light-375.png'),fullPage:true})
 await page.evaluate(()=>localStorage.setItem('theme','dark')); await page.reload()
 await page.locator('.project-theme-panel .theme-host').waitFor(); await button('主题导航').click(); await button('证据资料').click()
 await page.locator('.theme-host img').waitFor()
 check(await page.locator('.theme-host img').evaluate(img=>img.complete && img.naturalWidth>0),'深色主题真实PNG可读')
 await page.screenshot({path:path.join(out,'resource-dark-375.png'),fullPage:true})
 check(errors.length===0,'无浏览器脚本错误')
 check(requests.filter(r=>r.path.includes('/theme')).every(r=>r.status<400),'主题真实HTTP没有被stub或错误洗成成功')
 assert.deepEqual(await hashes(),frozen)
 const selected = await page.request.get(`${api}/api/projects/${fixture.projects[0].id}/theme`, {headers:{Authorization:`Bearer ${fixture.users[0].token}`}})
 const binding = await selected.json()
 check(binding.state==='ready' && binding.version.version===definition.theme.version,'独立HTTP回读版本和绑定一致')
 await writeFile(path.join(out,'browser-receipt.json'),JSON.stringify({checks,requests,scriptErrors:errors,sourceHashes:frozen,selected:{projectId:fixture.projects[0].id,versionId:binding.version.id,sourceId:binding.source.id,digest:binding.package.digest,generation:binding.generation}},null,2)+'\n')
 console.log(JSON.stringify({checks:checks.length,themeHttp:requests.filter(r=>r.path.includes('/theme')).length,scriptErrors:errors.length}))
} catch (error) {
 await page.screenshot({path:path.join(out,`failure-${stage}.png`),fullPage:true})
 console.log(JSON.stringify({stage,requests}))
 // eslint-disable-next-line preserve-caught-error -- Playwright原错误可能回显认证头，测试仅报告首行及脱敏请求元数据。
 throw new Error(error.message.split('\n')[0])
}
finally { await browser.close() }
