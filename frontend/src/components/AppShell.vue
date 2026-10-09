<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { PanelLeft, Sparkles } from 'lucide-vue-next'
import Sidebar from './Sidebar.vue'

defineProps({ title: { type: String, default: '探索好物' }, subtitle: { type: String, default: '你的个人选购空间' } })
const route = useRoute()
const mobile = ref(window.innerWidth <= 900)
const open = ref(!mobile.value)
const toggle = ref(null), panel = ref(null)
function resize() {
  const next = window.innerWidth <= 900
  if (next !== mobile.value) { mobile.value = next; open.value = !next }
}
function close() { if (mobile.value) { open.value = false; nextTick(() => toggle.value?.focus()) } }
function keydown(event) {
  if (!mobile.value || !open.value) return
  if (event.key === 'Escape') close()
  if (event.key === 'Tab') {
    const controls = panel.value?.querySelectorAll('button:not(:disabled), a, input')
    if (!controls?.length) return
    const first = controls[0], last = controls[controls.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus() }
  }
}
watch(open, async value => { if (value && mobile.value) { await nextTick(); panel.value?.querySelector('button')?.focus() } })
watch(() => route.path, close)
onMounted(() => { window.addEventListener('resize', resize); window.addEventListener('keydown', keydown) })
onUnmounted(() => { window.removeEventListener('resize', resize); window.removeEventListener('keydown', keydown) })
</script>
<template>
  <div :class="['workspace', { 'sidebar-closed': !open, 'menu-open': mobile && open }]">
    <Transition name="veil"><button v-if="mobile && open" class="sidebar-backdrop" aria-label="关闭导航" tabindex="-1" @click="close" /></Transition>
    <Transition name="sidebar">
      <div v-if="open" id="workspace-navigation" ref="panel" class="sidebar-frame" :role="mobile ? 'dialog' : undefined" :aria-modal="mobile || undefined" aria-label="工作区导航">
        <Sidebar :mobile="mobile" @navigate="close" @close="close" />
      </div>
    </Transition>
    <main class="chat-main" :inert="mobile && open">
      <header class="topbar">
        <button ref="toggle" class="icon" title="切换导航栏" aria-label="切换导航栏" aria-controls="workspace-navigation" :aria-expanded="open" @click="open = !open"><PanelLeft :size="19" /></button>
        <div class="topbar-title"><strong>{{ title }}</strong><span>{{ subtitle }}</span></div>
        <div class="model-label"><Sparkles :size="13" /><span>DeepSeek 驱动</span></div>
      </header>
      <slot />
    </main>
  </div>
</template>
