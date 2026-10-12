<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowUp, Square, Sparkles, Bookmark, LockKeyhole, Globe2 } from 'lucide-vue-next'
import { useChat } from '../stores/chat'
const chat = useChat(), text = ref(''), remember = ref(false), input = ref(null), submitting = ref(false)
const archived = computed(() => chat.sessions.find(s => s.id === chat.currentId)?.status === 'archived')
const blocked = computed(() => archived.value || submitting.value || chat.generating)
async function send() {
  const value = text.value.trim()
  if (!value || blocked.value) return
  const consent = remember.value
  text.value = ''; remember.value = false; submitting.value = true
  try { await chat.send(value, consent) } finally { submitting.value = false; await nextTick(); input.value?.focus() }
}
function keydown(event) { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); send() } }
async function setDraft(value) { if (blocked.value) return; text.value = value; await nextTick(); input.value?.focus() }
watch(text, async () => { await nextTick(); if (input.value) { input.value.style.height = 'auto'; input.value.style.height = Math.min(input.value.scrollHeight, 180) + 'px' } })
defineExpose({ setDraft })
</script>
<template>
  <form :class="['composer', { 'is-generating': chat.generating }]" @submit.prevent="send">
    <div class="search-mode-bar">
      <button type="button" :class="['web-search-toggle', { enabled: chat.webSearchEnabled }]" :aria-pressed="chat.webSearchEnabled" :disabled="blocked" @click="chat.webSearchEnabled = !chat.webSearchEnabled"><Globe2 :size="15" />联网补充<span class="mini-switch"></span></button>
      <span>{{ chat.webSearchEnabled ? '优先查本地 · 无候选时联网并保存资料' : '已关闭 · 仅使用本地商品资料' }}</span>
    </div>
    <div class="composer-entry"><Sparkles :size="19" class="composer-spark" /><textarea ref="input" v-model="text" aria-label="消息" :placeholder="archived ? '这个会话已归档，恢复后即可继续对话' : '想买什么？说说你的预算、用途，或一点小偏好…'" maxlength="4000" rows="1" :disabled="archived" @keydown="keydown"></textarea></div>
    <div class="composer-bottom"><button type="button" :class="['memory-toggle', { enabled: remember }]" :aria-pressed="remember" :disabled="archived || chat.generating" @click="remember = !remember"><Bookmark :size="14" />{{ remember ? '已允许记住本轮偏好' : '记住本轮偏好' }}<span class="mini-switch"></span></button><span class="input-hint">{{ text.length ? text.length + '/4000' : 'Enter 发送 · Shift + Enter 换行' }}</span><LockKeyhole v-if="archived" :size="17" class="muted" /><button v-if="chat.generating" type="button" class="send stop" title="停止生成" aria-label="停止生成" @click="chat.stop()"><Square :size="16" fill="currentColor" /></button><button v-else class="send" title="发送消息" aria-label="发送消息" :disabled="!text.trim() || blocked"><ArrowUp :size="21" /></button></div>
  </form>
</template>

