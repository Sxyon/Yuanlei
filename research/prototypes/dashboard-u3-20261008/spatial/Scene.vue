<script setup>
import {ref,computed,onMounted} from 'vue';
const scene=ref(null),theme=ref('light'),showRoute=ref(true),selected=ref(null);
const send=payload=>parent.postMessage(JSON.parse(JSON.stringify({channel:window.__CHANNEL__,...payload})),window.__HOST_ORIGIN__);
const colors={open:'#ddf3e8',setup:'#e3ebfc',blocked:'#ffddbd'};
const points=computed(()=>scene.value?.route.map(p=>p.map(v=>v*50).join(',')).join(' ')||'');
const pick=z=>{selected.value=z;send({type:'selected',id:z.id})};
window.addEventListener('message',e=>{if(e.source!==parent||e.origin!==window.__HOST_ORIGIN__||e.data?.channel!==window.__CHANNEL__||e.data.type!=='snapshot')return;scene.value=e.data.scene;selected.value=scene.value.zones.find(z=>z.id===e.data.selectedId)||null;theme.value=e.data.theme;document.documentElement.style.backgroundColor=theme.value==='dark'?'#172733':'#fff';showRoute.value=e.data.showRoute;});
onMounted(()=>send({type:'ready'}));
</script>
<template>
 <main :data-theme="theme">
  <template v-if="scene">
   <svg :viewBox="`0 0 ${scene.extent[0]*50} ${scene.extent[1]*50}`" role="img" aria-label="R2 合成空间区域与绕行路径">
    <rect x="0" y="0" :width="scene.extent[0]*50" :height="scene.extent[1]*50" :fill="theme==='dark'?'#1d303d':'#f7f9fb'" stroke="#83929b"/>
    <g v-for="z in scene.zones" :key="z.id" :data-zone="z.id" role="button" tabindex="0" :aria-label="z.label" @click="pick(z)" @keydown.enter="pick(z)" @keydown.space.prevent="pick(z)">
     <rect :x="z.rect[0]*50" :y="z.rect[1]*50" :width="z.rect[2]*50" :height="z.rect[3]*50" rx="5" :fill="colors[z.status]" stroke="#53677a" :stroke-dasharray="z.status==='blocked'?'5 3':undefined"/>
     <text :x="z.rect[0]*50+8" :y="z.rect[1]*50+28" fill="#182d3d" font-size="16">{{z.label}}</text>
    </g>
    <polyline v-if="showRoute" data-route="true" :points="points" fill="none" :stroke="theme==='dark'?'#81d4bf':'#116d69'" stroke-width="5" pointer-events="none"/>
   </svg>
   <p v-if="scene.zones.length===0">空场景：暂无区域和路径。</p>
   <p v-else-if="selected">{{selected.label}} · {{selected.status==='blocked'?'物料阻挡':selected.status==='setup'?'布置中':'开放'}}
    <button @click="send({type:'navigate',object:selected.object})">查看准确对象</button>
   </p>
   <p v-else>选择区域，核对其对象再进入办理。</p>
  </template>
  <p v-else>等待宿主合成快照…</p>
 </main>
</template>
