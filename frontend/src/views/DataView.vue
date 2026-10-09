<script setup>
import { ref, onMounted } from 'vue'
import { Upload, RefreshCw, Search, FileJson, ExternalLink, Globe2, Database, Layers, ArrowUpRight, LoaderCircle } from 'lucide-vue-next'
import AppShell from '../components/AppShell.vue'
import { useChat } from '../stores/chat'
import { api } from '../api'

const kind = ref('products')
const text = ref('[]')
const result = ref(null)
const sourceDraft = ref(null)
const conversion = ref(null)
const busy = ref(false)
const error = ref('')
const url = ref('')
onMounted(() => { useChat().loadSessions().catch(e => { error.value = e.message }) })

async function perform(fn) {
  if (busy.value) return
  error.value = ''
  busy.value = true
  try { result.value = await fn() } catch (e) { error.value = e.message } finally { busy.value = false }
}

async function extract() {
  sourceDraft.value = null
  conversion.value = null
  await perform(async () => {
    sourceDraft.value = await api('/sources/preview', 'POST', { url: url.value })
    return null
  })
}

async function convert() {
  await perform(async () => {
    conversion.value = await api('/sources/convert', 'POST', { draft_id: sourceDraft.value.draft_id })
    kind.value = 'products'
    text.value = JSON.stringify([conversion.value.product], null, 2)
    return null
  })
}

async function importData(status = null) {
  await perform(async () => {
    const records = JSON.parse(text.value)
    let payload = records
    if (status) {
      if (kind.value !== 'products' || !conversion.value || !Array.isArray(records) ||
          records.length !== 1 || records[0]?.id !== conversion.value.product.id) {
        throw new Error('商品 JSON 已变化，请重新生成后再确认导入。')
      }
      payload = [{ ...records[0], status }]
    }
    const response = await api(`/${kind.value}/import`, 'POST', payload)
    if (status && response.status === 'succeeded') {
      text.value = JSON.stringify(payload, null, 2)
    }
    return response
  })
}

async function upload(event) {
  const file = event.target.files[0]
  if (file) { try { text.value = await file.text(); conversion.value = null; error.value = '' } catch { error.value = '读取文件失败，请重新选择 JSON 文件。' } }
}
</script>

<template>
  <AppShell title="数据工作台" subtitle="每一份好建议，源于可靠资料">
  <div class="data-scroll"><div class="data-page">
    <header class="data-header"><div><span class="eyebrow">YOUR KNOWLEDGE STUDIO</span><h1>让好建议，有据可依<span class="heading-dot">.</span></h1><p class="muted">采集、核对与整理，为选物建立可信的产品资料库。</p></div><span class="studio-icon"><Database :size="30" :stroke-width="1.3" /></span></header>
    <div class="data-steps"><span><i>01</i>提取官网资料</span><ArrowUpRight :size="15" /><span><i>02</i>核对与导入</span><ArrowUpRight :size="15" /><span><i>03</i>建立检索索引</span></div>

    <section>
      <div class="panel-heading"><span class="panel-icon"><Globe2 :size="21" /></span><div><h2>从官网开始</h2><p>粘贴品牌官网链接，提取资料并生成待核对的商品草稿。</p></div><span class="panel-number">01</span></div>
      <form class="crawl-form" @submit.prevent="extract">
        <input v-model="url" type="url" placeholder="https://品牌官网/产品页面" aria-label="官网链接" required />
        <button :disabled="busy"><Search :size="17" />提取资料</button>
      </form>
      <div v-if="sourceDraft" class="source-draft">
        <div class="source-draft-title">
          <strong>{{ sourceDraft.title || '未提供网页标题' }}</strong>
          <a :href="sourceDraft.source_url" target="_blank" rel="noopener noreferrer" title="打开官网页面"><ExternalLink :size="16" /></a>
        </div>
        <small>草稿编号：{{ sourceDraft.draft_id }}</small>
        <ul v-if="sourceDraft.warnings?.length" class="draft-warnings"><li v-for="warning in sourceDraft.warnings" :key="warning">{{ warning }}</li></ul>
        <div class="data-actions"><button :disabled="busy || sourceDraft.warnings?.length" @click="convert"><FileJson :size="17" />生成商品 JSON</button></div>
        <details><summary>查看筛选后的产品正文</summary><pre class="result-json">{{ sourceDraft.text || '没有可提取的产品正文' }}</pre></details>
      </div>
      <div v-if="conversion" class="conversion-status">
        <strong>已生成商品草稿：{{ conversion.product.name }}</strong>
        <p>请核对下方 JSON。点击“确认并启用”即可一次导入并建立检索索引。</p>
        <p v-if="!conversion.product.specs?.storage_gb">当前草稿缺少存储容量；带容量要求的检索会过滤该商品。</p>
        <p>商品导入不包含价格快照；带预算的检索还需要导入对应价格。</p>
        <ul v-if="conversion.warnings.length"><li v-for="warning in conversion.warnings" :key="warning">{{ warning }}</li></ul>
      </div>
    </section>

    <section>
      <div class="panel-heading"><span class="panel-icon sand"><FileJson :size="21" /></span><div><h2>整理你的资料</h2><p>上传 JSON 文件，或直接编辑下方内容，核对后再导入。</p></div><span class="panel-number">02</span></div>
      <div class="data-toolbar">
        <label>资料类型<select v-model="kind"><option value="products">商品</option><option value="prices">价格快照</option><option value="reviews">评价</option></select></label>
        <input type="file" accept="application/json,.json" aria-label="选择 JSON 文件" @change="upload" />
      </div>
      <textarea v-model="text" class="json-input" aria-label="导入 JSON" spellcheck="false"></textarea>
      <div class="data-actions" v-if="kind === 'products' && conversion">
        <button class="primary" :disabled="busy" @click="importData('active')"><Upload :size="17" />确认并启用</button>
        <button :disabled="busy" @click="importData('draft')">仅保存草稿</button>
      </div>
      <button v-else class="primary" :disabled="busy" @click="importData()"><Upload :size="17" />导入</button>
    </section>

    <section class="maintenance-panel"><div class="panel-heading"><span class="panel-icon lavender"><Layers :size="21" /></span><div><h2>保持资料可检索</h2><p>导入后如出现检索缺失，可重新构建索引。</p></div></div><button :disabled="busy" @click="perform(() => api('/indexes/rebuild', 'POST'))"><RefreshCw :size="17" />修复索引</button></section>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="busy" class="data-busy" role="status"><LoaderCircle :size="17" class="spin" />正在处理资料，请稍候…</p>
    <pre v-if="result" class="result-json">{{ JSON.stringify(result, null, 2) }}</pre>
  </div></div>
  </AppShell>
</template>
