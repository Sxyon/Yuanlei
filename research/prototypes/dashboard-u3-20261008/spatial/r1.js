import {h} from '/runtime/vue.js';
export const definition={type:'coordinate-map',field:'scene',route:true};
/** 校验本次有限坐标素材输入，保留旧四类素材的拒绝证据。 */
export function validateDefinition(d){
 if(!d||Object.keys(d).some(k=>!['type','field','route'].includes(k))||d.type!=='coordinate-map'||d.field!=='scene'||typeof d.route!=='boolean')throw Error('仅接受有限 coordinate-map；没有代码、项目或 URL 输入');
}
/** 校验小空间样例的有界几何，供宿主读取两路线同一输入。 */
export function validateScene(s){
 if(!s?.synthetic||s.version!==1||s.project!=='alpha'||!Array.isArray(s.extent)||s.extent.length!==2||s.extent.some(v=>!Number.isFinite(v)||v<=0||v>50))throw Error('场景版本/项目/范围不合格');
 if(!Array.isArray(s.zones)||s.zones.length>12||!Array.isArray(s.route)||s.route.length>20)throw Error('区域或路径超过小样例边界');
 const seen=new Set();
 for(const z of s.zones){if(typeof z.id!=='string'||seen.has(z.id)||typeof z.label!=='string'||z.label.length>40||!['open','setup','blocked'].includes(z.status)||!Array.isArray(z.rect)||z.rect.length!==4)throw Error('区域输入不合格');seen.add(z.id);const[x,y,w,h]=z.rect;if(![x,y,w,h].every(Number.isFinite)||x<0||y<0||w<=0||h<=0||x+w>s.extent[0]||y+h>s.extent[1])throw Error('区域越过场地边界');}
 for(const p of s.route)if(!Array.isArray(p)||p.length!==2||p.some((v,i)=>!Number.isFinite(v)||v<0||v>s.extent[i]))throw Error('路径坐标越界');
 return s;
}
/** 按坐标绘制区域、阻挡和通行路径，点击只提出对象导航。 */
export function drawR1(scene,select,showRoute=true){
 validateDefinition(definition);validateScene(scene);const colors={open:'#ddf3e8',setup:'#e3ebfc',blocked:'#ffddbd'};
 return h('svg',{viewBox:`0 0 ${scene.extent[0]*50} ${scene.extent[1]*50}`,role:'img','aria-label':'R1 合成空间区域与绕行路径',class:'space-map'},[
 h('rect',{x:0,y:0,width:scene.extent[0]*50,height:scene.extent[1]*50,fill:'var(--soft)',stroke:'var(--line)'}),
 ...scene.zones.map(z=>h('g',{'data-zone':z.id,role:'button',tabindex:0,'aria-label':z.label,onClick:()=>select(z),onKeydown:e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();select(z)}}},[h('rect',{x:z.rect[0]*50,y:z.rect[1]*50,width:z.rect[2]*50,height:z.rect[3]*50,rx:5,fill:colors[z.status],stroke:'#53677a','stroke-dasharray':z.status==='blocked'?'5 3':undefined}),h('text',{x:z.rect[0]*50+8,y:z.rect[1]*50+28,fill:'#182d3d','font-size':16},z.label)])),
 showRoute?h('polyline',{'data-route':'true',points:scene.route.map(p=>p.map(v=>v*50).join(',')).join(' '),fill:'none',stroke:'var(--accent)','stroke-width':5,'pointer-events':'none'}):null
 ]);
}
