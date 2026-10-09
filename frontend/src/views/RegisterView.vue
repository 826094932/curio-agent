<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, Eye, EyeOff, LoaderCircle } from 'lucide-vue-next'
import AuthLayout from '../components/AuthLayout.vue'
import { api } from '../api'
import { useAuth } from '../stores/auth'
const nickname = ref(''), email = ref(''), password = ref(''), error = ref(''), busy = ref(false)
const showPassword = ref(false)
const auth = useAuth(), router = useRouter()
async function submit() {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await api('/auth/register', 'POST', { nickname: nickname.value, email: email.value, password: password.value }); await auth.login(email.value, password.value); await router.push('/') }
  catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>
<template>
  <AuthLayout>
    <form class="auth-form" @submit.prevent="submit">
      <span class="eyebrow">MAKE ROOM FOR BETTER CHOICES</span><h1>认识一下<span class="heading-dot">.</span></h1><p class="auth-intro">创建你的空间，让每次选购更合心意。</p>
      <label>怎么称呼你<input v-model="nickname" name="nickname" autocomplete="nickname" placeholder="你的昵称" maxlength="64" required /></label>
      <label>邮箱地址<input v-model="email" name="email" type="email" placeholder="you@example.com" autocomplete="email" required /></label>
      <label>设置密码<span class="password-field"><input v-model="password" name="password" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" minlength="8" maxlength="128" placeholder="至少 8 位字符" required /><button type="button" class="icon" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" :size="18" /><Eye v-else :size="18" /></button></span></label>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <button class="primary auth-submit" :disabled="busy"><LoaderCircle v-if="busy" class="spin" :size="18" />{{ busy ? '正在创建你的空间…' : '开启选物之旅' }}<ArrowRight v-if="!busy" :size="18" /></button>
      <p class="auth-switch">已经有账号？<RouterLink to="/login">欢迎回来 <span>↗</span></RouterLink></p>
    </form>
  </AuthLayout>
</template>
