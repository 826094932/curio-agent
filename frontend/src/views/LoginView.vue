<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, LoaderCircle } from 'lucide-vue-next'
import AuthLayout from '../components/AuthLayout.vue'
import { useAuth } from '../stores/auth'
const email = ref(''), password = ref(''), error = ref(''), busy = ref(false)
const showPassword = ref(false)
const auth = useAuth(), router = useRouter()
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await auth.login(email.value, password.value); await router.push('/') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <AuthLayout>
    <form class="auth-form" @submit.prevent="submit">
      <span class="eyebrow">YOUR PERSONAL SPACE</span><h1>欢迎回来<span class="heading-dot">.</span></h1><p class="auth-intro">继续探索，找到下一件适合你的好物。</p>
      <label>邮箱地址<input v-model="email" name="email" type="email" placeholder="you@example.com" autocomplete="email" required /></label>
      <label>密码<span class="password-field"><input v-model="password" name="password" :type="showPassword ? 'text' : 'password'" placeholder="输入你的密码" autocomplete="current-password" minlength="8" maxlength="128" required /><button type="button" class="icon" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" :size="18" /><Eye v-else :size="18" /></button></span></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="primary auth-submit" :disabled="busy"><LoaderCircle v-if="busy" class="spin" :size="18" />{{ busy ? '正在进入你的空间…' : '进入我的空间' }}<ArrowRight v-if="!busy" :size="18" /></button>
      <p class="auth-switch">还没有账号？<RouterLink to="/register">创建账号 <span>↗</span></RouterLink></p>
    </form>
  </AuthLayout>
</template>
