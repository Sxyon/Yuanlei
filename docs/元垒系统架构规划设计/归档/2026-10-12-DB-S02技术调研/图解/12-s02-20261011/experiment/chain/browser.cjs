/** 用真实DOM核对持久主题及迁入环境，不依赖截图单独断言。 */
const {chromium}=require(process.env.S02_PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs');const path=require('node:path');const assert=require('node:assert/strict');
(async()=>{
 const root=path.resolve('docs/元垒系统架构规划设计/图解/12-s02-20261011/chain-browser');fs.mkdirSync(root,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'chrome'});const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[],requests=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>requests.push(r.url()));
 await page.route('**/file/notes?generation=*',route=>route.fulfill({status:200,contentType:'text/markdown',body:'# Synthetic Markdown probe\n![outside](https://example.invalid/pixel.png)\n[outside](https://example.invalid/leave)\n<script>window.markdownExecuted=true</script>'}));
 await page.goto('http://127.0.0.1:5192');await page.getByRole('button',{name:'区域储能的技术可行性',exact:true}).waitFor();
 assert.equal(await page.locator('.project-bar strong').textContent(),'Synthetic A · target project');
 await page.getByRole('button',{name:'default · 0.1-lab',exact:true}).click();await page.locator('nav button[aria-current=page]').filter({hasText:'Dashboard'}).waitFor();
 await page.screenshot({path:path.join(root,'a-persisted-default.png'),fullPage:true});
 await page.getByRole('button',{name:'工作台',exact:true}).click();await page.waitForFunction(()=>document.querySelector('article img')?.naturalWidth===320);assert.match(await page.locator('article.json pre').textContent(),/"environment": "A"/);
 await page.frameLocator('iframe').getByRole('heading',{name:'Static synthetic A'}).waitFor();
 await page.getByRole('button',{name:'research · 0.1-lab',exact:true}).click();await page.getByRole('button',{name:'课题脉络',exact:true}).waitFor();
 await page.getByRole('heading',{name:'Synthetic Markdown probe',exact:true}).waitFor();assert.equal(await page.evaluate(()=>window.markdownExecuted===true),false);
 assert.equal(await page.locator('article.markdown img, article.markdown a, article.markdown script').count(),0);assert.equal(requests.some(url=>url.startsWith('https://example.invalid/')),false);
 await page.getByRole('button',{name:'区域储能的技术可行性',exact:true}).click();assert.match(await page.locator('.host h2').textContent(),/topics \/ a-topic-1/);await page.getByRole('button',{name:'返回主题原页面',exact:true}).click();assert.equal(await page.locator('nav button[aria-current=page]').textContent(),'课题脉络');
 await page.getByRole('button',{name:'环境 B',exact:true}).click();await page.getByRole('button',{name:'区域储能的技术可行性',exact:true}).waitFor();assert.equal(await page.locator('.project-bar strong').textContent(),'Synthetic B · target project');
 await page.screenshot({path:path.join(root,'b-imported-research.png'),fullPage:true});
 await page.getByRole('button',{name:'证据资料',exact:true}).click();assert.match(await page.locator('article.json pre').textContent(),/"samples": 37/);await page.waitForFunction(()=>document.querySelector('article img')?.naturalWidth===320);
 await page.frameLocator('iframe').getByRole('heading',{name:'Static synthetic B'}).waitFor();
 await page.screenshot({path:path.join(root,'b-target-files.png'),fullPage:true});
 await page.getByRole('button',{name:'返回宿主',exact:true}).click();assert.match(await page.locator('.host h2').textContent(),/project \/ b-energy/);await page.getByRole('button',{name:'返回主题原页面',exact:true}).click();assert.equal(await page.locator('nav button[aria-current=page]').textContent(),'证据资料');
 await page.reload();await page.getByRole('button',{name:'区域储能的技术可行性',exact:true}).waitFor();assert.equal(await page.locator('.version-bar strong').textContent(),'持久选择：课题调研 0.1-lab');
 // 延迟A系统响应；环境切换后释放，旧数据不得覆盖B。
 let unblock;const released=new Promise(resolve=>unblock=resolve);let seen;const reached=new Promise(resolve=>seen=resolve);let completed;const routed=new Promise(resolve=>completed=resolve);
 await page.route('**/A/_chain/a-energy/system',async route=>{seen();await released;await route.continue();completed()});
 await page.getByRole('button',{name:'重新加载',exact:true}).click();await reached;
 await page.getByRole('button',{name:'环境 B',exact:true}).click();await page.getByRole('button',{name:'区域储能的技术可行性',exact:true}).waitFor();unblock();await routed;await page.unroute('**/A/_chain/a-energy/system');
 await page.waitForLoadState('networkidle');assert.equal(await page.locator('.project-bar strong').textContent(),'Synthetic B · target project');
 await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'narrow.png'),fullPage:true});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(errors,[]);
 const result={twoThemesFourPages:true,componentMechanism:'Native Vue dynamic component fixed registry; no FormKit/TinyEngine',persistedSelectionAfterReload:true,sourceObject:'a-topic-1',targetProject:'b-energy',targetSamples:37,pngWidth:320,hostReturn:'b-energy -> research/证据资料',lateSourceResponseCannotReplaceTarget:true,pageErrors:errors,narrowOverflow:false,markdownProbeReached:true,markdownScriptExecuted:false,markdownProbe:'Browser-fulfilled synthetic input; external image/link/raw script inert',scope:'Real migrated package/PG/file HTTP and Vue DOM; synthetic identity/business/host operation'};
 fs.writeFileSync(path.join(root,'browser-checks.json'),JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
