<script setup>
import { computed, onMounted, ref } from 'vue'
import { Smartphone, Laptop, Headphones, Monitor, Watch, RefreshCw, ArrowUpRight, Sparkles, SlidersHorizontal, ShieldCheck, Search, Check } from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import MessageList from '../components/MessageList.vue'
import ChatInput from '../components/ChatInput.vue'
import ProductComparison from '../components/ProductComparison.vue'
import { useChat } from '../stores/chat'

const chat = useChat(), composer = ref(null), category = ref('all')
const title = computed(() => chat.sessions.find(s => s.id === chat.currentId)?.title || '探索好物')
const archived = computed(() => chat.sessions.find(s => s.id === chat.currentId)?.status === 'archived')
const categories = [{ id: 'all', label: '为你精选', icon: Sparkles }, { id: 'phone', label: '手机', icon: Smartphone }, { id: 'laptop', label: '电脑', icon: Laptop }, { id: 'headphone', label: '耳机', icon: Headphones }, { id: 'monitor', label: '显示器', icon: Monitor }, { id: 'watch', label: '手表', icon: Watch }]
const ideas = [
  { category: 'phone', icon: Smartphone, tone: 'sage', tag: '记录日常', title: '好照片，不必高预算', detail: '寻找拍照与续航兼顾的手机', budget: '预算 ¥3,000', prompt: '预算 3000 元，想买拍照和续航比较好的手机' },
  { category: 'headphone', icon: Headphones, tone: 'sand', tag: '通勤时光', title: '让世界，安静一点', detail: '为每天的通勤选一副降噪耳机', budget: '预算 ¥1,000', prompt: '通勤用降噪耳机，预算 1000 元，佩戴舒适很重要' },
  { category: 'monitor', icon: Monitor, tone: 'lavender', tag: '专注工作', title: '给灵感，多一点空间', detail: '适合写代码的清晰大屏', budget: '预算 ¥1,500', prompt: '预算 1500 元，推荐一台适合写代码的显示器' },
  { category: 'laptop', icon: Laptop, tone: 'sage', tag: '轻装出发', title: '工作与生活，随身带走', detail: '兼顾便携与性能的轻薄笔记本', budget: '预算 ¥6,000', prompt: '预算 6000 元，推荐一台适合编程、便携的笔记本电脑' },
  { category: 'watch', icon: Watch, tone: 'sand', tag: '运动搭子', title: '每一步，都值得记录', detail: '寻找适合跑步和日常佩戴的手表', budget: '预算 ¥1,500', prompt: '预算 1500 元，想买一块适合跑步和日常佩戴的智能手表' },
]
const visibleIdeas = computed(() => category.value === 'all' ? ideas.slice(0, 3) : ideas.filter(item => item.category === category.value))
const stages = { understanding: '正在理解你的需求', search_products: '正在寻找合适的产品', get_product_details: '正在核对产品参数', get_current_prices: '正在核对价格信息', search_reviews: '正在整理使用评价', compare_products: '正在对比候选产品', get_user_preference: '正在读取你的偏好', save_user_preference: '正在记住你的偏好' }
function choose(prompt) { composer.value?.setDraft(prompt) }
async function recover() { try { await chat.recover() } catch (e) { chat.error = e.message } }
onMounted(async () => {
  try {
    await chat.loadSessions()
    const previous = sessionStorage.getItem('current_session_id')
    if (!chat.currentId && previous && chat.sessions.some(s => s.id === previous)) await chat.select(previous)
  } catch (e) { chat.error = e.message }
})
</script>
<template>
  <AppShell :title="title">
    <div class="conversation-scroll">
      <div v-if="!chat.messages.length" class="empty-chat">
        <section class="welcome-hero">
          <div class="hero-copy"><span class="eyebrow"><span class="tiny-line"></span>为你的下一件好物</span><h1>少一点纠结，<br />多一点<span class="serif-accent">刚刚好。</span></h1><p>告诉我你的预算与日常。<br />一起找到真正适合你的电子产品。</p><div class="hero-proof"><span><ShieldCheck :size="14" />资料有据可查</span><span><SlidersHorizontal :size="14" />依据你的偏好</span></div></div>
          <div class="hero-art" aria-hidden="true"><div class="hero-orbit"></div><div class="hero-orbit orbit-inner"></div><span class="orbit-spark">✦</span><div class="hero-device"><Headphones :size="104" :stroke-width="1.1" /></div><div class="hero-mini-device"><Smartphone :size="49" :stroke-width="1.2" /></div><div class="hero-note"><span class="check-circle"><Check :size="13" /></span><div>为你而选<small>需求 · 预算 · 偏好</small></div></div><span class="art-caption">GOOD THINGS. RIGHT FIT.</span></div>
        </section>
        <section class="discover-section"><div class="section-heading"><div><span class="eyebrow">一点灵感</span><h2>从一个日常场景开始</h2></div><span class="muted small">选个话题，随时调整</span></div>
          <div class="category-tabs" aria-label="商品类别"><button v-for="item in categories" :key="item.id" :class="{ selected: category === item.id }" :aria-pressed="category === item.id" @click="category = item.id"><component :is="item.icon" :size="15" />{{ item.label }}</button></div>
          <TransitionGroup name="cards" tag="div" class="suggestions"><button v-for="(item, index) in visibleIdeas" :key="item.category" :class="['suggestion-card', item.tone]" :style="{ '--delay': (index * 65) + 'ms' }" :disabled="chat.generating || archived" @click="choose(item.prompt)"><div class="card-top"><span class="category-symbol"><component :is="item.icon" :size="25" :stroke-width="1.5" /></span><ArrowUpRight class="card-arrow" :size="19" /></div><span class="card-tag">{{ item.tag }}</span><h3>{{ item.title }}</h3><p>{{ item.detail }}</p><span class="budget">{{ item.budget }}</span></button></TransitionGroup>
        </section>
      </div>
      <MessageList v-else />
      <ProductComparison />
    </div>
    <div class="composer-area">
      <Transition name="status"><div v-if="chat.stage" class="stage" role="status"><span class="thinking-dots"><i></i><i></i><i></i></span>{{ stages[chat.stage] || '正在整理回答' }}<span class="stage-hint">选物正在为你工作</span></div></Transition>
      <Transition name="status"><div v-if="chat.error" class="error chat-error" role="alert">{{ chat.error }}<button v-if="chat.requestId" class="icon" title="查询运行结果" @click="recover"><RefreshCw :size="16" /></button></div></Transition>
      <ChatInput ref="composer" /><p class="disclaimer"><Search :size="11" />推荐供选购参考，价格与参数请以来源页面为准。</p>
    </div>
  </AppShell>
</template>

