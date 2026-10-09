<script setup>
import { ref, watch, nextTick, onUnmounted } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { Sparkles, UserRound, Copy, Check, ChevronUp } from 'lucide-vue-next'
import { useChat } from '../stores/chat'
const chat = useChat(), container = ref(null), copied = ref('')
const copyError = ref(''), loadingOlder = ref(false)
let copyTimer
function markdown(text) { return DOMPurify.sanitize(marked.parse(text || ''), { FORBID_TAGS: ['img', 'iframe', 'style'], FORBID_ATTR: ['style'] }) }
async function copy(item) { try { await navigator.clipboard.writeText(item.content); copied.value = item.id; copyError.value = ''; clearTimeout(copyTimer); copyTimer = setTimeout(() => { copied.value = '' }, 1800) } catch { copyError.value = '复制失败，请选择文字手动复制。' } }
async function older() {
  if (loadingOlder.value) return
  const scroll = container.value?.closest('.conversation-scroll'), height = scroll?.scrollHeight || 0
  loadingOlder.value = true
  try { await chat.older(); await nextTick(); if (scroll) scroll.scrollTop += scroll.scrollHeight - height } catch (e) { chat.error = e.message } finally { loadingOlder.value = false }
}
onUnmounted(() => clearTimeout(copyTimer))
watch(() => [chat.messages.length, chat.messages.at(-1)?.content], async () => {
  const scroll = container.value?.closest('.conversation-scroll')
  const nearBottom = !scroll || scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 160
  await nextTick()
  if (scroll && nearBottom) scroll.scrollTop = scroll.scrollHeight
})
</script>
<template>
  <div ref="container" class="messages" aria-live="polite">
    <button v-if="chat.cursor" class="load-older" :disabled="loadingOlder" @click="older"><ChevronUp :size="14" />{{ loadingOlder ? '正在加载…' : '查看更早的对话' }}</button>
    <article v-for="item in chat.messages" :key="item.id" :class="['message', item.role]">
      <div class="avatar"><UserRound v-if="item.role === 'user'" :size="18" /><Sparkles v-else :size="18" /></div>
      <div class="message-body">
        <div class="message-label">{{ item.role === 'user' ? '你' : '选物' }}<span v-if="item.partial && !chat.generating" class="muted small">未完成</span></div>
        <div v-if="item.role === 'assistant'" class="markdown" v-html="markdown(item.content)"></div>
        <p v-else class="user-text">{{ item.content }}</p>
        <div v-if="!item.content && chat.generating" class="thinking-placeholder" role="status"><span class="thinking-dots"><i></i><i></i><i></i></span><span>正在为你整理思路</span></div>
        <button v-if="item.content && item.role === 'assistant'" class="copy" :title="copied === item.id ? '已复制' : '复制回答'" @click="copy(item)"><Check v-if="copied === item.id" :size="14" /><Copy v-else :size="14" />{{ copied === item.id ? '已复制' : '复制' }}</button>
      </div>
    </article>
    <p v-if="copyError" class="error small" role="alert">{{ copyError }}</p>
  </div>
</template>
