import { computed, inject } from 'vue'

/** 仅转换开发者提供的界面词汇；业务正文和历史快照由调用者原样显示。 */
export function useProjectThemeVocabulary() {
  const context = inject('projectThemeContext', null)
  const topicLabel = computed(() => context?.value?.package?.theme.topicLabel || '议题')
  const themeText = text => text.replace(/议题|课题/g, topicLabel.value)
  return { topicLabel, themeText }
}
