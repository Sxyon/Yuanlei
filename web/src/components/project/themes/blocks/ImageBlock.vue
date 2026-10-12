<script setup>
import { onUnmounted, ref, watch } from 'vue'
const props = defineProps({ block: { type: Object, required: true }, result: { type: Object, required: true } })
const source = ref('')
const decodeError = ref(false)
defineEmits(['retry'])
watch(() => props.result.bytes, bytes => {
  if (source.value) URL.revokeObjectURL(source.value)
  decodeError.value = false
  source.value = URL.createObjectURL(new Blob([bytes], { type: props.result.metadata.mediaType }))
}, { immediate: true })
onUnmounted(() => { if (source.value) URL.revokeObjectURL(source.value) })
function failDecode() { decodeError.value = true; if (source.value) URL.revokeObjectURL(source.value); source.value = '' }
</script>
<template><figure class="theme-image"><div v-if="decodeError" class="theme-state error" role="alert"><p>PNG 图像无法解码，请核对资料内容。</p><button @click="$emit('retry')">重新读取图像</button></div><img v-else :src="source" :alt="block.alt" @error="failDecode" /><figcaption>{{ block.alt }} · {{ result.metadata.size }} bytes</figcaption></figure></template>
