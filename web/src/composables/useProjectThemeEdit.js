import { inject, onActivated, onDeactivated, onUnmounted, onMounted } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { Modal } from 'ant-design-vue'

/** 编辑Owner登记实际未保存输入；失活页面不参与当前离开确认。 */
export function useProjectThemeEdit(label, projectId, dirty, discard, busy = () => false, protectRoute = false) {
  const register = inject('registerProjectThemeEdit', null)
  if (!register) return
  let remove
  const editor = {get label() { return typeof label === 'function' ? label() : label },projectId,dirty,discard,busy}
  const activate = () => { remove?.(); remove = register(editor) }
  if (protectRoute) {
    onBeforeRouteLeave(() => {
      if (busy()) return false
      if (!dirty()) return true
      return new Promise(resolve => Modal.confirm({title:`放弃未保存内容：${editor.label}？`,okText:'放弃所列修改并离开',cancelText:'返回编辑',onOk:()=>{discard();resolve(true)},onCancel:()=>resolve(false)}))
    })
    const beforeUnload = event => {if(dirty()){event.preventDefault();event.returnValue=''}}
    onMounted(() => {if(typeof window !== 'undefined')window.addEventListener('beforeunload',beforeUnload)})
    onUnmounted(() => {if(typeof window !== 'undefined')window.removeEventListener('beforeunload',beforeUnload)})
  }
  activate()
  onActivated(activate)
  onDeactivated(() => remove?.())
  onUnmounted(() => remove?.())
  return editor
}
