<script setup>
import { Smartphone, Headphones, Laptop, ArrowUpRight, Check, Fingerprint } from 'lucide-vue-next'
import BrandMark from './BrandMark.vue'
</script>
<template>
  <main class="auth-layout">
    <section class="auth-story">
      <div class="auth-brand"><BrandMark /><strong>选物<span>CURATED BY YOU</span></strong></div>
      <div class="auth-story-content"><span class="eyebrow light">LESS NOISE. BETTER CHOICES.</span><h1>每一次选择，<br />都更懂你。</h1><p>把预算、需求和偏好交给选物。<br />从真实资料出发，找到适合你的下一件。</p>
        <div class="auth-art" aria-hidden="true"><div class="orbit orbit-one"></div><div class="orbit orbit-two"></div><div class="art-device art-laptop"><Laptop :size="95" :stroke-width="1" /><span>灵感 · 随时在线</span></div><div class="art-device art-phone"><Smartphone :size="55" :stroke-width="1.2" /></div><div class="art-device art-headphones"><Headphones :size="52" :stroke-width="1.2" /></div><div class="art-note"><span><Check :size="15" /></span>刚刚好，才最好。<ArrowUpRight :size="15" /></div></div>
      </div>
      <div class="auth-story-footer"><span>电子产品 · 个性化决策</span><span>为你的真实需求而选</span></div>
    </section>
    <section class="auth-panel"><div class="auth-panel-top"><BrandMark /><span>让选择，简单一点。</span></div><slot /><p class="auth-privacy"><Fingerprint :size="16" />你的会话与偏好，保存在你的个人空间</p></section>
  </main>
</template>
