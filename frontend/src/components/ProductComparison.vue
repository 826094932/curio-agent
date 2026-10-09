<script setup>
import { ExternalLink, Star, Smartphone, Laptop, Headphones, Monitor, Tablet, Watch, LayoutGrid, Table2, ArrowUpRight, ShieldCheck } from 'lucide-vue-next'
import { ref, watch } from 'vue'
import { api } from '../api'
import { useChat } from '../stores/chat'
const chat = useChat(), rating = ref(0), error = ref(''), view = ref('cards'), saving = ref(false)
const icons = { phone: Smartphone, laptop: Laptop, headphone: Headphones, monitor: Monitor, tablet: Tablet, smartwatch: Watch }
const labels = { phone: '手机', laptop: '笔记本', headphone: '耳机', monitor: '显示器', tablet: '平板', smartwatch: '智能手表' }
const safeLink = url => /^https?:\/\//i.test(url || '') ? url : undefined
const price = p => p.price?.final_price != null ? '¥' + Number(p.price.final_price).toLocaleString('zh-CN') : '暂无价格'
watch(() => chat.recommendationId, () => { rating.value = 0; error.value = '' })
async function feedback(value) {
  if (saving.value) return
  const id = chat.recommendationId
  saving.value = true
  try { await api('/feedback', 'POST', { recommendation_id: id, rating: value }); if (chat.recommendationId === id) { rating.value = value; error.value = '' } }
  catch (e) { if (chat.recommendationId === id) error.value = e.message } finally { saving.value = false }
}
</script>
<template>
  <section v-if="chat.products.length || chat.sources.length" class="comparison">
    <div v-if="chat.products.length" class="section-heading comparison-heading"><div><span class="eyebrow">THE SHORTLIST</span><h2>值得比较的选择 <span class="count-pill">{{ chat.products.length }}</span></h2></div><div class="view-toggle" aria-label="对比展示方式"><button :class="{ selected: view === 'cards' }" aria-label="卡片视图" :aria-pressed="view === 'cards'" @click="view = 'cards'"><LayoutGrid :size="16" /></button><button :class="{ selected: view === 'table' }" aria-label="表格视图" :aria-pressed="view === 'table'" @click="view = 'table'"><Table2 :size="16" /></button></div></div>
    <div v-if="chat.products.length && view === 'cards'" class="product-grid">
      <article v-for="p in chat.products" :key="p.id" class="product-card"><div class="product-visual"><span>{{ labels[p.category] || '电子产品' }}</span><component :is="icons[p.category] || Smartphone" :size="56" :stroke-width="1.1" /><a v-if="safeLink(p.source_url)" :href="safeLink(p.source_url)" target="_blank" rel="noopener noreferrer" :aria-label="'查看 ' + p.name + ' 的来源'"><ArrowUpRight :size="18" /></a></div><div class="product-info"><h3>{{ p.name }}</h3><div class="product-price">{{ price(p) }}<small>价格快照</small></div><p class="price-date">{{ p.price?.channel || '未提供价格来源' }}<template v-if="p.price?.captured_at"> · {{ p.price.captured_at.slice(0, 10) }}</template><span v-if="p.price?.is_stale" class="stale">已过期</span></p><div class="score-row"><span>规格评分</span><strong>{{ p.total_score ?? '—' }}</strong></div><details v-if="Object.keys(p.dimension_scores || {}).length"><summary>查看各项评分</summary><div v-for="(value, key) in p.dimension_scores" :key="key" class="dimension-row"><span>{{ key }}</span><strong>{{ value }}</strong></div></details><p v-if="p.missing_fields?.length" class="missing-data">待补充：{{ p.missing_fields.join('、') }}</p></div></article>
    </div>
    <div v-if="chat.products.length && view === 'table'" class="table-scroll"><table><thead><tr><th>产品</th><th>价格快照</th><th>规格评分</th><th>缺失数据</th></tr></thead><tbody>
      <tr v-for="p in chat.products" :key="p.id"><td><component :is="icons[p.category] || Smartphone" :size="18" /><strong>{{ p.name }}</strong><a v-if="safeLink(p.source_url)" :href="safeLink(p.source_url)" target="_blank" rel="noopener noreferrer" title="查看产品来源"><ExternalLink :size="14" /></a></td><td>{{ price(p) }}<small>{{ p.price?.channel }} · {{ p.price?.captured_at?.slice(0, 10) }}{{ p.price?.is_stale ? ' · 已过期' : '' }}</small></td><td>{{ p.total_score ?? '—' }}<small v-for="(value, key) in p.dimension_scores" :key="key">{{ key }}: {{ value }}</small></td><td>{{ p.missing_fields?.join('、') || '无' }}</td></tr>
    </tbody></table></div>
    <details v-if="chat.sources.length" class="sources-panel"><summary><ShieldCheck :size="16" />这份建议的依据 <span>{{ chat.sources.length }} 条来源</span></summary><ol><li v-for="source in chat.sources" :key="source.id"><a :href="safeLink(source.url)" target="_blank" rel="noopener noreferrer">{{ source.id }}<ExternalLink :size="12" /></a><p>{{ source.text }}</p></li></ol></details>
    <div v-if="chat.recommendationId" class="feedback"><span class="muted small">这次建议，有帮到你吗？</span><div class="rating-stars"><button v-for="n in 5" :key="n" class="icon" :title="n + ' 分'" :aria-label="n + ' 分'" :aria-pressed="rating === n" :disabled="saving" @click="feedback(n)"><Star :size="18" :fill="rating >= n ? '#be9453' : 'none'" :color="rating >= n ? '#be9453' : 'currentColor'" /></button></div><span class="small feedback-thanks" role="status">{{ saving ? '正在保存…' : rating ? '谢谢，让我们更懂你。' : '' }}</span></div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </section>
</template>

