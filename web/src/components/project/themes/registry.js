import SummaryBlock from './blocks/SummaryBlock.vue'
import RecordsBlock from './blocks/RecordsBlock.vue'
import TopicBlock from './blocks/TopicBlock.vue'
import DiscussionBlock from './blocks/DiscussionBlock.vue'
import JsonBlock from './blocks/JsonBlock.vue'
import ImageBlock from './blocks/ImageBlock.vue'

// 平台静态导入；定义只能选择这些名字，不能提供SFC、JS或运行时模块路径。
export const themeComponentRegistry = Object.freeze({ summary: SummaryBlock, records: RecordsBlock, topic: TopicBlock, discussion: DiscussionBlock, json: JsonBlock, image: ImageBlock })
