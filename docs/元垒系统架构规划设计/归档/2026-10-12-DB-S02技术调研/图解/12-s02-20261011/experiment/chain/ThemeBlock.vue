<script setup>
import { computed } from 'vue'
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { createDashboardSrcdoc } from '@static-frame'
const props = defineProps(['block', 'system', 'resources', 'openObject'])
const markdown = new MarkdownIt({ html: false }).disable(['image', 'link'])
const markdownHtml = computed(() => DOMPurify.sanitize(markdown.render(props.resources.notes || '')))
</script>
<template><article :class="block.type"><h3>{{ block.title }}</h3>
            <template v-if="block.type==='summary'"><p class="big">{{ system?.project.name }}</p><p>{{ system?.project.description }}</p><span class="source">系统HTTP · synthetic fixture</span></template>
            <template v-else-if="block.type==='records'"><ul><li v-for="item in system?.[block.binding]" :key="item.id"><button @click="openObject(block.binding,item.id)">{{ item.title }}</button><span>{{ item.state }}</span></li></ul><span class="source">稳定对象：{{ block.binding }} · 点击交给宿主</span></template>
            <template v-else-if="block.type==='json'"><pre>{{ resources.metrics }}</pre><span class="source">指定项目文件 · metrics.json</span></template>
            <template v-else-if="block.type==='image'"><img :src="resources.image" alt="合成项目资料图"><span class="source">指定项目文件 · PNG字节 / Blob URL</span></template>
            <template v-else-if="block.type==='html'"><iframe title="隔离静态报告" sandbox referrerpolicy="no-referrer" :srcdoc="createDashboardSrcdoc(resources.report || '')"></iframe><span class="source">服务端静态策略＋CSP · 无业务脚本</span></template>
            <template v-else-if="block.type==='markdown'"><div v-html="markdownHtml"></div><span class="source">Markdown · 禁止原始HTML / DOMPurify</span></template>
          </article></template>
