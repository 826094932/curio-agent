<script setup>
import { computed, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Plus, Pencil, Archive, ArchiveRestore, Trash2, LogOut, Database, MessageSquare, Search, Compass, X, ArrowUpRight } from 'lucide-vue-next'
import BrandMark from './BrandMark.vue'
import { useAuth } from '../stores/auth'
import { useChat } from '../stores/chat'
defineProps({ mobile: Boolean })
const emit = defineEmits(['navigate', 'close'])
const auth = useAuth(), chat = useChat(), router = useRouter(), route = useRoute()
const editing = ref(null), title = ref(''), error = ref(''), archived = ref(false), query = ref('')
const sessions = computed(() => chat.sessions.filter(s => (s.status === 'archived') === archived.value && s.title.toLowerCase().includes(query.value.toLowerCase())))
async function action(fn) { try { await fn(); error.value = '' } catch (e) { error.value = e.message } }
async function navigate(fn) { await action(async () => { await fn(); await router.push('/'); emit('navigate') }) }
async function rename(id) { if (!title.value.trim()) return; await action(() => chat.edit(id, { title: title.value.trim() })); editing.value = null }
async function remove(id) { if (confirm('删除这个会话？')) await action(() => chat.remove(id)) }
async function logout() { chat.stop(); await action(async () => { await auth.logout(); chat.$reset(); await router.push('/login') }) }
</script>
<template>
  <aside class="sidebar">
    <div class="brand"><BrandMark /><div><strong>选物<span class="brand-period">.</span></strong><span class="brand-caption">让每一次选择更值得</span></div><button v-if="mobile" class="icon sidebar-close" aria-label="关闭导航" @click="emit('close')"><X :size="19" /></button></div>
    <button class="new-chat" :disabled="chat.generating" @click="navigate(() => chat.create())"><Plus :size="19" /><span>开启新对话</span><ArrowUpRight :size="16" /></button>
    <RouterLink to="/" :class="['sidebar-link', { current: route.path === '/' }]" @click="emit('navigate')"><Compass :size="18" />选购助手<span class="nav-dot"></span></RouterLink>
    <RouterLink v-if="auth.user?.is_admin" to="/data" :class="['sidebar-link', { current: route.path === '/data' }]" @click="emit('navigate')"><Database :size="18" />数据工作台</RouterLink>
    <div class="sidebar-divider"></div>
    <div class="sidebar-label"><span>你的对话 <small>{{ sessions.length }}</small></span><button class="icon" :class="{ 'archive-active': archived }" :title="archived ? '查看活跃会话' : '查看已归档会话'" :aria-pressed="archived" @click="archived = !archived"><Archive :size="15" /></button></div>
    <label class="session-search"><Search :size="15" /><input v-model="query" aria-label="搜索会话" :placeholder="archived ? '搜索已归档会话' : '搜索历史对话'" /><button v-if="query" class="icon" aria-label="清除搜索" @click="query = ''"><X :size="13" /></button></label>
    <nav class="session-list" aria-label="会话列表">
      <TransitionGroup name="sessions"><article v-for="s in sessions" :key="s.id" :class="['session', { active: s.id === chat.currentId }]">
        <form v-if="editing === s.id" @submit.prevent="rename(s.id)"><input v-model="title" maxlength="255" aria-label="会话名称" @keydown.esc="editing = null" /><button :disabled="!title.trim()" title="保存名称">保存</button><button type="button" @click="editing = null">取消</button></form>
        <template v-else><button class="session-title" :disabled="chat.generating" @click="navigate(() => chat.select(s.id))"><MessageSquare :size="15" /><span>{{ s.title }}</span></button><div class="session-actions"><button class="icon" title="重命名" :disabled="chat.generating" @click="editing = s.id; title = s.title"><Pencil :size="13" /></button><button class="icon" :title="s.status === 'archived' ? '恢复会话' : '归档会话'" :disabled="chat.generating" @click="action(() => chat.edit(s.id, { status: s.status === 'active' ? 'archived' : 'active' }))"><ArchiveRestore v-if="s.status === 'archived'" :size="13" /><Archive v-else :size="13" /></button><button class="icon" title="删除会话" :disabled="chat.generating" @click="remove(s.id)"><Trash2 :size="13" /></button></div></template>
      </article></TransitionGroup>
      <div v-if="!sessions.length" class="session-empty"><MessageSquare :size="23" :stroke-width="1.2" /><span>{{ query ? '没有找到匹配的对话' : archived ? '还没有归档的对话' : '你的下一次好选择，从这里开始' }}</span></div>
    </nav>
    <p v-if="error" class="error small" role="alert">{{ error }}</p>
    <div class="sidebar-note"><span class="note-star">✦</span><strong>好选择，始于了解你。</strong><p>预算、用途、小偏好，<br />都可以慢慢告诉我。</p></div>
    <footer><span class="user-avatar">{{ (auth.user?.nickname || '你').slice(0, 1) }}</span><div class="user-info"><strong>{{ auth.user?.nickname || '我的账户' }}</strong><small>个人选购空间</small></div><button class="icon" title="退出登录" @click="logout"><LogOut :size="17" /></button></footer>
  </aside>
</template>

