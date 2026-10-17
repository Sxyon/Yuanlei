<script setup>
import { useProjectThemeVocabulary } from '@/composables/useProjectThemeVocabulary'
const { themeText } = useProjectThemeVocabulary()

import { computed, ref, watch } from 'vue'
import MarkdownPreview from '@/components/common/MarkdownPreview.vue'
import { blueprintDocumentHeading, blueprintDocumentBody } from '@/utils/blueprintName'
const props = defineProps({ presentation: { type: String, required: true }, projectId: { type: String, required: true }, blueprint: { type: Object, default: null }, activity: { type: Array, default: () => [] }, topics: { type: Array, default: () => [] }, decisions: { type: Array, default: () => [] }, loading: Boolean, simulation: Boolean })
const selectedId = ref('')
watch(() => props.topics, items => { if (!items.some(item => item.id === selectedId.value)) selectedId.value = items[0]?.id || '' }, { immediate: true })
const selected = computed(() => props.topics.find(item => item.id === selectedId.value))
const conclusions = computed(() => props.decisions.filter(item => item.topic_id === selectedId.value))
const heading = computed(() => props.blueprint ? blueprintDocumentHeading(props.blueprint.name, props.blueprint.content) : '')
const target = (query = {}) => props.simulation ? {} : { name: 'ProjectTopics', params: { project_id: props.projectId }, query }
const blueprintTarget = computed(() => props.simulation ? {} : { name: 'ProjectBlueprints', params: { project_id: props.projectId }, query: props.blueprint ? { blueprint: props.blueprint.name } : {} })
/** 保留原事件的准确对象与讨论定位。 */
function activityTarget(item) {
  return target({ ...(item.topic_id || item.kind === 'topic' ? { topic_id: item.topic_id || item.id } : {}), ...(item.kind === 'decision' ? { decision_id: item.id } : item.kind === 'comment' ? { comment_id: item.comment_id || item.id } : {}) })
}
</script>
<template>
  <div class="themed-overview" :class="presentation" :data-overview-presentation="presentation">
    <header class="reading-heading"><small>{{ presentation === 'focus' ? '项目总览' : '研究工作室' }}</small><h1>{{ presentation === 'focus' ? '把这一件事推进清楚' : '阅读，形成有依据的判断' }}</h1></header>
    <div class="reading-grid">
      <nav v-if="presentation === 'research'" class="topic-directory" :aria-label="themeText('课题目录')"><h2>{{ themeText('课题目录') }}</h2><button v-for="item in topics" :key="item.id" :aria-current="selectedId === item.id ? 'true' : undefined" @click="selectedId=item.id">{{item.title}}</button><p v-if="!topics.length && !loading">{{ themeText('尚无课题') }}</p></nav>
      <article v-if="presentation === 'research'" class="question-paper"><small>研究问题</small><template v-if="selected"><h2>{{selected.title}}</h2><MarkdownPreview :content="selected.summary || '尚未填写问题正文。'" /><h3>预期结果</h3><MarkdownPreview :content="selected.expected_outcome || '尚未填写预期结果。'" /><h3>已记录决定</h3><article v-for="item in conclusions" :key="item.id" class="recorded-decision"><p>{{item.conclusion || '未填写结论'}}</p><small>{{item.status}}</small><RouterLink v-if="!simulation" :to="target({topic_id:selectedId,decision_id:item.id})">查看决定原文与历史</RouterLink></article><p v-if="!conclusions.length" class="empty">暂无已记录决定。保留研究问题，不从讨论生成判断。</p><RouterLink v-if="!simulation" :to="target({topic_id:selectedId})">{{ themeText('进入准确课题与讨论 →') }}</RouterLink></template><template v-else-if="!loading"><h2>从一个问题开始</h2><p>{{ themeText('这里呈现当前项目的真实课题。') }}</p><RouterLink v-if="!simulation" :to="target()">{{ themeText('前往议题') }}</RouterLink></template></article>
      <section class="blueprint-paper" :class="{'research-context':presentation==='research'}"><small>{{presentation === 'focus' ? '蓝图 / PROJECT BLUEPRINT' : '研究背景 · 蓝图'}}</small><template v-if="blueprint"><h2>{{heading}}</h2><MarkdownPreview :content="blueprintDocumentBody(blueprint.content) || '这份蓝图尚无正文。'" /><footer>{{blueprint.name}}</footer></template><template v-else-if="!loading"><h2>还没有项目蓝图</h2><p>从一份清晰的目标开始，记录边界和完成条件。</p></template><RouterLink v-if="!simulation" :to="blueprintTarget">{{blueprint ? '打开蓝图 →' : '前往蓝图'}}</RouterLink></section>
      <section class="reading-activity" aria-label="最近动态"><h2>最近动态</h2><article v-for="item in activity" :key="item.event_key" class="reading-event"><time>{{new Date(item.created_at).toLocaleString('zh-CN')}}</time><RouterLink v-if="!simulation" :to="activityTarget(item)">{{item.title}}</RouterLink><strong v-else>{{item.title}}</strong><small>{{{topic:themeText('议题'),comment:'讨论',decision:'决定'}[item.kind]}} · {{item.author_name}}</small></article><p v-if="!activity.length && !loading" class="empty">{{ themeText('还没有最近动态。产生议题、讨论或决定动态后，在这里读取原始记录。') }}</p></section>
    </div>
  </div>
</template>
<style scoped lang="less">
.themed-overview{padding:28px 0;color:var(--color-text);}.reading-heading{margin-bottom:28px;small{color:var(--color-text-secondary);letter-spacing:2px;}h1{font-size:28px;font-weight:600;margin:12px 0;line-height:1.5;}}
.reading-grid{display:grid;gap:28px;align-items:start;grid-template-columns:minmax(0,2fr) minmax(210px,1fr);}.blueprint-paper,.question-paper{background:var(--gray-0);padding:32px;border:1px solid var(--gray-150);border-radius:4px;min-width:0;h2{font-size:25px;line-height:1.7;margin:18px 0;}h3{font-size:17px;margin-top:28px;}small,footer{color:var(--color-text-secondary);font-size:12px;}footer{margin:28px 0 16px;}p{line-height:1.9;}:deep(.yk-markdown-preview){font-size:16px;line-height:1.95;}}
.reading-activity{padding:4px 0;min-width:0;h2{font-size:17px;margin:0 0 20px;}}.reading-event{display:grid;gap:8px;padding:18px 0;border-top:1px solid var(--gray-150);overflow-wrap:anywhere;time,small{font-size:11px;color:var(--color-text-secondary);}a,strong{font-size:14px;font-weight:500;}}
.empty{font-size:13px;color:var(--color-text-secondary);line-height:1.8;}.research .reading-grid{grid-template-columns:180px minmax(0,1fr) minmax(190px,.65fr);gap:22px;}.topic-directory{grid-column:1;grid-row:1 / span 2;h2{font-size:15px;margin:0 0 18px;}button{display:block;width:100%;border:0;border-left:2px solid transparent;background:none;padding:14px 12px;text-align:left;color:var(--color-text-secondary);font:inherit;line-height:1.8;cursor:pointer;}button[aria-current]{border-color:var(--main-color);background:var(--main-10);color:var(--main-color);}}
.question-paper{grid-column:2;grid-row:1 / span 2;}.research-context{grid-column:3;grid-row:1;padding:20px;h2{font-size:17px;}:deep(.yk-markdown-preview){font-size:13px;}}.research .reading-activity{grid-column:3;grid-row:2;}.recorded-decision{padding:16px 0;border-bottom:1px solid var(--gray-150);a{display:block;margin-top:12px;}}a{overflow-wrap:anywhere;}button:focus-visible,a:focus-visible{outline:2px solid var(--main-color);outline-offset:3px;}
@media(max-width:1200px){.research .reading-grid{grid-template-columns:150px minmax(0,1fr);}.research-context{grid-column:2;grid-row:3;}.research .reading-activity{grid-column:2;grid-row:4;}.question-paper{grid-row:1 / span 2;}}
@media(max-width:760px){.reading-grid,.research .reading-grid{display:flex;flex-direction:column;}.reading-grid>*{width:100%;box-sizing:border-box;}.blueprint-paper,.question-paper{padding:20px;}.reading-heading h1{font-size:23px;}.topic-directory button{padding:12px;}}
</style>
