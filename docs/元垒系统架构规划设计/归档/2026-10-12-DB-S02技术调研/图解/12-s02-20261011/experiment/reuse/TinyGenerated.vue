<template>
<div class="tiny-output">
<h2 >TinyEngine 真实出码验证</h2>
<p >同一 Vue/Vite 编译宿主</p></div></template>

<script setup>
import * as vue from "vue"
import { defineProps,defineEmits } from "vue"
import { I18nInjectionKey } from "vue-i18n"




const props = defineProps({  })




const emit = defineEmits([])
const { t, lowcodeWrap, stores } = vue.inject(I18nInjectionKey).lowcode()
const wrap = lowcodeWrap(props, { emit })
wrap({ stores })


const state = vue.reactive({  })
wrap({ state })









</script>
<style  scoped> .tiny-output { padding: 24px; } </style>
