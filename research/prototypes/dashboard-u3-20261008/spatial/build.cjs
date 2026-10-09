/** 编译固定合成 SFC，限制依赖并输出本地忽略构建产物。 */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto'),{createRequire}=require('node:module');
const root=path.resolve(__dirname,'../../../..'),requireWeb=createRequire(path.join(root,'web/package.json'));
const {parse,compileScript}=requireWeb('vue/compiler-sfc'),esbuild=requireWeb('esbuild');
const output=path.join(__dirname,'../.build');fs.mkdirSync(output,{recursive:true});
async function compile(source){
 const parsed=parse(source,{filename:'Scene.vue'});if(parsed.errors.length)throw Error('SFC parse failed: '+parsed.errors.join(';'));
 const compiled=compileScript(parsed.descriptor,{id:'u3-spatial',inlineTemplate:true});
 const component=compiled.content.replace('export default','const __default__ =');
 const result=await esbuild.build({stdin:{contents:component+'\nimport {createApp} from "vue";createApp(__default__).mount("#scene");',resolveDir:path.join(root,'web'),sourcefile:'Scene.vue',loader:'js'},bundle:true,write:false,format:'iife',minify:true,platform:'browser',define:{'process.env.NODE_ENV':'"production"',__VUE_OPTIONS_API__:'false',__VUE_PROD_DEVTOOLS__:'false',__VUE_PROD_HYDRATION_MISMATCH_DETAILS__:'false'},plugins:[{name:'fixed-dependency',setup(b){b.onResolve({filter:/.*/},args=>{if(args.kind==='import-statement'&&!['vue','@vue/runtime-dom','@vue/runtime-core','@vue/shared','@vue/reactivity'].includes(args.path)&&!args.path.startsWith('.'))return{errors:[{text:'dependency_not_allowed: '+args.path}]};});}}]});
 return result.outputFiles[0].text;
}
(async()=>{const source=fs.readFileSync(path.join(__dirname,'Scene.vue'),'utf8');const bundle=await compile(source);
 const variants={normal:bundle,crash:bundle+';throw Error("synthetic_mount_failure");',probe:bundle+`;
 const probe={};try{parent.document.body.dataset.r2Probe='escaped';probe.parentDOM='escaped'}catch(e){probe.parentDOM=e.name}
 try{sessionStorage.setItem('r2-probe','escaped');probe.storage='escaped'}catch(e){probe.storage=e.name}
 fetch('http://127.0.0.1:8767/sample-data?project=alpha&binding=monthly-alpha').then(()=>probe.network='escaped').catch(e=>{probe.network=e.name;parent.postMessage({channel:window.__CHANNEL__,type:'probe',probe},window.__HOST_ORIGIN__)});
 parent.postMessage({channel:window.__CHANNEL__,type:'navigate',url:'https://example.invalid/'},window.__HOST_ORIGIN__);
 `};
 for(const [name,js]of Object.entries(variants))fs.writeFileSync(path.join(output,`r2-${name}.json`),JSON.stringify({bundle:js,sha256:crypto.createHash('sha256').update(js).digest('hex')})+'\n');
 const negative=[];for(const [name,s]of [['compile','<template><div></template>'],['dependency','<script setup>import x from "not-approved-library"</script><template><div>{{x}}</div></template>']]){try{await compile(s);throw Error('negative unexpectedly accepted')}catch(e){if(e.message==='negative unexpectedly accepted')throw e;negative.push({name,error:e.message.slice(0,220)})}}
 const report={round:'2026-10-08',executedAt:new Date().toISOString(),vue:requireWeb('vue/package.json').version,compiler:requireWeb('vue/compiler-sfc').version,esbuild:esbuild.version,sfcBytes:Buffer.byteLength(source),bundleBytes:Buffer.byteLength(bundle),bundleSha256:crypto.createHash('sha256').update(bundle).digest('hex'),negative,scope:'fixed hand-authored synthetic SFC; no agent generation'};
 fs.writeFileSync(path.join(__dirname,'../evidence/spatial-build.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
})().catch(e=>{console.error(e);process.exit(1)});
