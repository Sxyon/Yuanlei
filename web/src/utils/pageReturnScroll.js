import { nextTick, onActivated, onDeactivated, onMounted, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRoute } from 'vue-router'

const positions = new Map()
export function clearReturnScroll() { positions.clear() }
/** 在来源页面回读结束后恢复其滚动；位置只存在当前登录会话内。 */
export function useReturnScroll(loading, container) {
  const route = useRoute()
  let active = true, pendingRestore = true
  const save = (from) => {
    const node = container()
    if (node) {
      const focused = typeof document !== 'undefined' ? document.activeElement : null
      const link = focused?.closest?.('a[href]')
      positions.set(from.fullPath, { top: node.scrollTop, href: node.contains?.(link) ? link?.getAttribute('href') : null })
    }
  }
  const restore = async () => {
    if (!active || !pendingRestore || loading.value) return
    const path = route.fullPath
    await nextTick()
    if (active && !loading.value && route.fullPath === path) {
      const node = container()
      const position = positions.get(path)
      if (node && position) {
        node.scrollTop = position.top
        if (typeof document !== 'undefined' && document.activeElement === document.body && position.href?.startsWith('/')) {
          Array.from(node.querySelectorAll('a[href]')).find(link => link.getAttribute('href') === position.href)?.focus({ preventScroll: true })
        }
      }
      pendingRestore = false
    }
  }
  onBeforeRouteLeave((_to, from) => save(from))
  onBeforeRouteUpdate((to, from) => { save(from); if (to.path !== from.path) pendingRestore = true })
  onDeactivated(() => { active = false })
  onActivated(() => { active = true; pendingRestore = true; void restore() })
  onMounted(restore)
  watch(loading, (pending) => { if (!pending) void restore() })
}
