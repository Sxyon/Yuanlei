import {FILES} from './data.js';
export const escape=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function markdown(text){
 // 只展示预置合成 Markdown；未实现真实文档解析。
 let rows=text.split('\n'),out=[],table=[];
 const flush=()=>{if(table.length){out.push('<div class="table-wrap"><table class="compact-table">'+table.filter(x=>!/^\|[-:|\s]+\|$/.test(x)).map((x,i)=>'<tr>'+x.split('|').slice(1,-1).map(v=>`<${i?'td':'th'}>${escape(v.trim())}</${i?'td':'th'}>`).join('')+'</tr>').join('')+'</table></div>');table=[]}};
 for(const line of rows){if(line.startsWith('|')){table.push(line);continue}flush();if(/^### /.test(line))out.push('<h3>'+escape(line.slice(4))+'</h3>');else if(/^## /.test(line))out.push('<h2>'+escape(line.slice(3))+'</h2>');else if(/^# /.test(line))out.push('<h2>'+escape(line.slice(2))+'</h2>');else if(line.startsWith('- '))out.push('<p>✓ '+escape(line.slice(2))+'</p>');else if(line.trim())out.push('<p>'+escape(line)+'</p>')}
 flush();return out.join('');
}
export function content(fid,result){let text=FILES[fid].text;if(result?.revision===1&&text)text=text.replaceAll('三个年度','两个年度').replace('当前 R3 示例','旧要求 R2 对照示例').replace('三个年度资料已标注来源。','两个年度资料已标注来源；第三年度未补齐。');return text}
