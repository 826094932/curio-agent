<script setup>
import { computed, onMounted, ref } from 'vue'
import { RefreshCw, ArrowDownToLine, ExternalLink, FileCheck2, Search, LoaderCircle, Check, X, History, ChevronRight } from 'lucide-vue-next'
import { api } from '../api'

const labels = { pending: '待提取', processing: '提取中', draft: '待审核', extract_failed: '提取失败', index_pending: '索引待重试', succeeded: '已入库', rejected: '已忽略' }
const eventLabels = { extraction_started: '开始提取官网', draft_created: '生成商品草稿', draft_edited: '修改商品草稿', extraction_failed: '提取失败', mysql_committed: '保存正式商品', indexed: '检索索引已更新', index_failed: '索引更新失败', rejected: '忽略这条资料' }
const filter = ref('')
const page = ref(1)
const listing = ref({ items: [], total: 0, counts: {} })
const selected = ref(null)
const officialUrl = ref('')
const editor = ref('')
const replacements = ref([])
const note = ref('')
const busy = ref('')
const loading = ref(false)
const error = ref('')
const notice = ref('')
const canPrepare = computed(() => ['pending', 'draft', 'extract_failed'].includes(selected.value?.status))
const shownProduct = computed(() => {
  if (['succeeded', 'index_pending'].includes(selected.value?.status)) {
    return [...selected.value.events].reverse().find(entry => entry.type === 'mysql_committed')?.after || selected.value.preview?.existing_product || selected.value.draft
  }
  return selected.value?.draft
})
const proofFor = key => shownProduct.value?.specs[key] === selected.value?.draft?.specs[key] ? selected.value.field_evidence['specs.' + key] : null
const pendingCount = computed(() => ['pending', 'draft', 'extract_failed', 'index_pending'].reduce((sum, key) => sum + (listing.value.counts[key] || 0), 0))
const maxPage = computed(() => Math.max(1, Math.ceil(listing.value.total / 12)))
const display = value => value == null ? '未记录' : typeof value === 'object' ? JSON.stringify(value) : String(value)
const date = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—'
const host = value => { try { return new URL(value).hostname } catch { return '网页资料' } }
const specNames = { battery_hours: '续航（小时）', battery_mah: '电池容量（mAh）', battery_wh: '电池容量（Wh）', weight_g: '重量（克）', latency_ms: '延迟（ms）', storage_gb: '存储容量（GB）', ram_gb: '内存（GB）', charging_w: '充电功率（W）', refresh_hz: '刷新率（Hz）', brightness_nits: '亮度（尼特）', screen_inches: '屏幕尺寸（英寸）', resolution_pixels: '分辨率像素数', noise_cancelling: '降噪', supports_nfc: 'NFC', panel: '面板类型', cpu: '处理器', gpu: '图形处理器', chip: '芯片', camera: '相机', color: '颜色', os: '操作系统', summary: '简介', status: '启用状态' }
const fieldName = key => specNames[key.replace('specs.', '')] || key

function setDetail(value) {
  selected.value = value
  officialUrl.value = value.page_url || value.source_url
  editor.value = JSON.stringify({ product: value.draft, field_evidence: value.field_evidence }, null, 2)
  replacements.value = []
  note.value = value.review_note || ''
}

async function load() {
  loading.value = true
  try {
    listing.value = await api(`/product-updates?status=${filter.value}&page=${page.value}&limit=12`)
    if (page.value > maxPage.value) { page.value = maxPage.value; await load() }
  } catch (e) { error.value = e.message } finally { loading.value = false }
}

async function choose(item) {
  if (busy.value) return
  error.value = ''; notice.value = ''; busy.value = '读取记录'
  try { setDetail(await api(`/product-updates/${item.id}`)) } catch (e) { error.value = e.message } finally { busy.value = '' }
}

async function changeFilter(value) { filter.value = value; page.value = 1; await load() }

async function act(name, fn, success) {
  if (busy.value) return
  error.value = ''; notice.value = ''; busy.value = name
  try {
    const result = await fn()
    if (result.id) setDetail(result)
    notice.value = result.error_message || success
    await load()
  } catch (e) {
    error.value = e.message
    // 冲突后重新获取当前差异，避免继续审批旧版本。
    if (e.status === 409 && selected.value) {
      try { setDetail(await api(`/product-updates/${selected.value.id}`)) } catch { /* 保留原有错误 */ }
    }
  } finally { busy.value = '' }
}

function prepare() {
  act('正在提取官网并生成草稿', () => api(`/product-updates/${selected.value.id}/prepare`, 'POST', { version: selected.value.version, url: officialUrl.value }), '草稿已生成，请核对参数与原文依据。')
}
function save() {
  act('正在保存草稿', () => {
    const edited = JSON.parse(editor.value)
    return api(`/product-updates/${selected.value.id}/draft`, 'PATCH', { ...edited, version: selected.value.version })
  }, '草稿已保存，差异预览已更新。')
}
function approve() {
  act('正在入库并更新索引', () => api(`/product-updates/${selected.value.id}/approve`, 'POST', { version: selected.value.version, target_hash: selected.value.preview.target_hash, replace_fields: replacements.value }), '商品已正式入库，可参与本地检索与推荐。')
}
function retry() {
  act('正在重试索引', () => api(`/product-updates/${selected.value.id}/retry-index`, 'POST', { version: selected.value.version }), '检索索引已更新。')
}
function reject() {
  act('正在保存审核结果', () => api(`/product-updates/${selected.value.id}/reject`, 'POST', { version: selected.value.version, note: note.value }), '已忽略，记录与依据仍保留。')
}
onMounted(load)
</script>

<template>
  <section class="updates-panel" aria-label="商品更新记录">
    <div class="panel-heading">
      <span class="panel-icon"><History :size="21" /></span>
      <div><h2>商品更新记录 <span class="update-count">{{ pendingCount }} 待处理</span></h2><p>联网发现的资料先留在这里，审核通过后加入正式商品库。</p></div>
    </div>
    <div class="update-toolbar">
      <div class="update-filters" aria-label="筛选更新记录">
        <button v-for="key in ['', 'pending', 'draft', 'succeeded', 'index_pending', 'extract_failed', 'rejected']" :key="key" :class="{ active: filter === key }" :disabled="!!busy" @click="changeFilter(key)">{{ key ? labels[key] : '全部' }}<small v-if="key && listing.counts[key]">{{ listing.counts[key] }}</small></button>
      </div>
      <div class="update-utility">
        <button :disabled="!!busy || loading" @click="load" title="刷新记录"><RefreshCw :size="15" :class="{ spin: loading }" /><span>刷新</span></button>
        <button :disabled="!!busy" @click="act('正在同步历史资料', () => api('/product-updates/sync', 'POST'), '已同步此前保存的网页资料。')"><ArrowDownToLine :size="15" />同步历史资料</button>
      </div>
    </div>

    <p v-if="error" class="error update-message" role="alert">{{ error }}</p>
    <p v-if="notice" class="update-message update-notice" role="status">{{ notice }}</p>
    <p v-if="busy" class="update-message update-progress" role="status"><LoaderCircle :size="15" class="spin" />{{ busy }}…</p>

    <div class="update-workspace" :class="{ 'with-detail': selected }">
      <div class="update-inbox">
        <div v-if="!listing.items.length" class="update-empty"><FileCheck2 :size="30" :stroke-width="1.2" /><strong>{{ filter ? '暂无此状态的记录' : '还没有待处理资料' }}</strong><p>开启联网补充并获取资料后，记录会自动出现在这里。已有资料可点击“同步历史资料”。</p></div>
        <button v-for="item in listing.items" :key="item.id" class="update-row" :class="{ selected: selected?.id === item.id }" :disabled="!!busy" @click="choose(item)">
          <div class="update-row-top"><span class="update-status" :class="item.status">{{ labels[item.status] }}</span><small>{{ host(item.source_url) }}</small></div>
          <strong>{{ item.product_name || item.title }}</strong>
          <div class="update-row-bottom"><small>{{ date(item.captured_at) }}</small><ChevronRight :size="15" /></div>
        </button>
        <div v-if="listing.total" class="update-pagination"><small>{{ listing.total }} 条记录 · {{ page }}/{{ maxPage }}</small><div><button :disabled="page <= 1 || !!busy" @click="page--; load()">上一页</button><button :disabled="page >= maxPage || !!busy" @click="page++; load()">下一页</button></div></div>
      </div>

      <div v-if="selected" class="update-detail">
        <header class="update-detail-head"><div><span class="update-status" :class="selected.status">{{ labels[selected.status] }}</span><h3>{{ shownProduct?.name || selected.title }}</h3></div><button class="update-close" aria-label="关闭记录详情" :disabled="!!busy" @click="selected = null"><X :size="17" /></button></header>
        <a class="update-source-link" :href="selected.source_url" target="_blank" rel="noopener noreferrer">查看发现来源 <ExternalLink :size="13" /></a>
        <p v-if="selected.error_message" class="update-record-error">{{ selected.error_message }}</p>

        <form v-if="canPrepare" class="update-extract" @submit.prevent="prepare">
          <label for="update-official-url">官网产品 / 参数页</label>
          <input id="update-official-url" v-model="officialUrl" type="url" required placeholder="https://品牌官网/产品参数页" :disabled="!!busy" />
          <button :disabled="!!busy"><Search :size="15" />{{ selected.draft?.model ? '重新提取' : '生成商品草稿' }}</button>
          <small>读取具体官网正文并提取一款商品；第三方资料可保留为线索，请先换成官网链接。</small>
        </form>

        <div v-if="shownProduct?.model" class="update-product">
          <div class="update-product-meta"><span>{{ shownProduct.brand }}</span><strong>{{ shownProduct.model }}</strong></div>
          <p class="update-product-summary">{{ shownProduct.summary }}</p>
          <div class="update-specs"><div v-for="(value, key) in shownProduct.specs" :key="key"><span>{{ fieldName(key) }}</span><strong>{{ typeof value === 'boolean' ? (value ? '支持' : '不支持') : display(value) }}</strong><details v-if="proofFor(key)"><summary>原文依据</summary><p>{{ proofFor(key) }}</p></details><small v-else>沿用原商品资料</small></div></div>
          <p class="update-price-note">商品入库不包含价格。涉及预算的推荐，还需要对应的价格快照。</p>
          <ul v-if="selected.warnings?.length" class="update-warnings"><li v-for="warning in selected.warnings" :key="warning">{{ warning }}</li></ul>
        </div>

        <div v-if="selected.preview && selected.status === 'draft'" class="update-preview">
          <h4>{{ selected.preview.mode === 'insert' ? '将新增一款正式商品' : '已找到同型号与配置的商品' }}</h4>
          <p v-if="selected.preview.existing_product">{{ selected.preview.existing_product.name }} · 默认补充缺失字段，已有参数冲突需要逐项勾选。</p>
          <div v-for="change in selected.preview.additions" :key="change.field" class="update-change"><Check :size="14" /><span>补充 {{ fieldName(change.field) }}：{{ display(change.new) }}</span></div>
          <label v-for="change in selected.preview.conflicts" :key="change.field" class="update-conflict"><input v-model="replacements" type="checkbox" :value="change.field" :disabled="!!busy" /><span><strong>替换 {{ fieldName(change.field) }}</strong><small>{{ display(change.old) }} → {{ display(change.new) }}</small></span></label>
          <p v-if="selected.preview.mode === 'existing' && !selected.preview.conflicts.length">本次没有新增参数，确认后复用现有商品并核对检索索引。</p>
          <button class="update-approve" :disabled="!!busy" @click="approve"><FileCheck2 :size="16" />审核通过，加入商品库</button>
        </div>

        <button v-if="selected.status === 'index_pending'" class="update-approve" :disabled="!!busy" @click="retry"><RefreshCw :size="16" />重试检索索引</button>
        <p v-if="selected.status === 'succeeded'" class="update-complete"><Check :size="17" />已加入正式商品库，检索索引已同步。</p>

        <details v-if="selected.status === 'draft'" class="update-disclosure"><summary>编辑草稿与原文依据</summary><p>可修正或删除字段；型号和每项规格必须保留官网逐字原文依据。保存后会重新校验并刷新差异。</p><textarea v-model="editor" aria-label="编辑商品草稿与依据" spellcheck="false" :disabled="!!busy"></textarea><button :disabled="!!busy" @click="save">保存并校验草稿</button></details>
        <details class="update-disclosure"><summary>查看发现的网页摘录</summary><p>{{ selected.source_content }}</p></details>
        <details v-if="selected.page_text" class="update-disclosure"><summary>查看提取的官网正文</summary><a :href="selected.page_url" target="_blank" rel="noopener noreferrer">打开官网 <ExternalLink :size="12" /></a><pre>{{ selected.page_text }}</pre></details>
        <details v-if="selected.events.length" class="update-disclosure"><summary>处理记录与耗时</summary><dl class="update-timing"><template v-for="(value, key) in selected.timings" :key="key"><dt>{{ ({ page_ms: '正文提取', structure_ms: '模型结构化', extract_total_ms: '草稿总耗时', mysql_ms: '商品入库', index_ms: '索引更新' })[key] || key }}</dt><dd>{{ (value / 1000).toFixed(2) }} 秒</dd></template></dl><ol class="update-history"><li v-for="(entry, index) in selected.events" :key="index"><strong>{{ eventLabels[entry.type] || entry.type }}</strong><small>{{ date(entry.at) }}</small><details v-if="entry.before || entry.after"><summary>变更明细</summary><pre>{{ JSON.stringify({ before: entry.before, after: entry.after, replaced_fields: entry.replaced_fields }, null, 2) }}</pre></details></li></ol></details>

        <div v-if="canPrepare" class="update-reject"><input v-model="note" maxlength="500" aria-label="忽略原因" placeholder="不适合入库？可填写原因" :disabled="!!busy" /><button :disabled="!!busy" @click="reject">忽略这条资料</button></div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.updates-panel { color: #282828; }
.update-count { display: inline-flex; margin-left: 8px; padding: 3px 8px; border-radius: 6px; background: #f3f3f3; font-size: 11px; font-weight: 500; vertical-align: middle; color: #666; }
.update-toolbar { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px; margin: 22px 0 16px; }
.update-filters, .update-utility { display: flex; flex-wrap: wrap; gap: 5px; }
.update-filters button, .update-utility button { font-size: 11px; padding: 7px 9px; background: transparent; border: 1px solid transparent; border-radius: 7px; color: #666; }
.update-filters button.active { background: #242424; color: #fff; }
.update-filters small { margin-left: 5px; opacity: .7; }
.update-utility button { display: inline-flex; align-items: center; gap: 5px; border-color: #e5e5e5; }
.update-workspace { display: grid; gap: 20px; }
.update-workspace.with-detail { grid-template-columns: minmax(190px, .75fr) minmax(0, 1.5fr); }
.update-inbox, .update-detail { min-width: 0; }
.update-inbox { display: flex; flex-direction: column; gap: 9px; }
.update-row { display: block; width: 100%; text-align: left; padding: 15px; background: #fff; border: 1px solid #e9e9e9; border-radius: 11px; transition: border-color .2s, background .2s; }
.update-row:hover, .update-row.selected { background: #fafafa; border-color: #888; }
.update-row-top, .update-row-bottom { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.update-row-top small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #888; font-size: 10px; }
.update-row>strong { display: block; font-size: 13px; line-height: 1.6; margin: 9px 0; overflow-wrap: anywhere; }
.update-row-bottom { color: #929292; font-size: 10px; }
.update-status { display: inline-block; flex-shrink: 0; font-size: 10px; padding: 3px 7px; border-radius: 5px; color: #666; background: #f1f1f1; }
.update-status.draft { color: #222; background: #e9e9e9; }
.update-status.succeeded { color: #fff; background: #363636; }
.update-status.extract_failed, .update-status.index_pending { color: #965315; background: #fff3e6; }
.update-detail { padding: 19px; border: 1px solid #e5e5e5; border-radius: 12px; background: #fcfcfc; align-self: start; }
.update-detail-head { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
.update-detail h3 { margin: 10px 0 8px; font-size: 17px; line-height: 1.5; overflow-wrap: anywhere; }
.update-close { padding: 4px; background: transparent; border: 0; }
.update-source-link { display: inline-flex; gap: 6px; align-items: center; color: #777; font-size: 11px; margin-bottom: 16px; }
.update-extract { display: flex; flex-wrap: wrap; gap: 9px; }
.update-extract label, .update-extract small { width: 100%; }
.update-extract label { font-size: 12px; font-weight: 600; }
.update-extract input { width: 100%; min-width: 0; font-size: 12px; color: #333; padding: 10px; }
.update-extract button, .update-detail>button, .update-preview button { display: inline-flex; gap: 7px; align-items: center; padding: 9px 12px; font-size: 12px; }
.update-extract small { color: #888; font-size: 11px; line-height: 1.7; }
.update-product { border-top: 1px solid #e8e8e8; margin-top: 20px; padding-top: 18px; }
.update-product-meta { display: flex; flex-wrap: wrap; gap: 8px; font-size: 13px; }
.update-product-meta span { color: #888; }
.update-product-summary, .update-price-note, .update-preview>p, .update-disclosure>p { font-size: 12px; line-height: 1.8; color: #777; }
.update-price-note { padding: 10px; background: #f2f2f2; border-radius: 7px; font-size: 11px; }
.update-specs { display: grid; gap: 8px; margin: 14px 0; }
.update-specs>div { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 4px; border-bottom: 1px solid #ececec; padding-bottom: 8px; }
.update-specs span { font-size: 11px; color: #888; overflow-wrap: anywhere; }
.update-specs strong { font-size: 12px; }
.update-specs details { grid-column: 1/-1; font-size: 11px; color: #777; }
.update-specs details p { padding: 8px; background: #f0f0f0; border-radius: 6px; line-height: 1.7; }
.update-preview { margin: 18px 0; padding: 15px; border: 1px solid #dedede; border-radius: 10px; background: white; }
.update-preview h4 { margin: 0; font-size: 13px; }
.update-change { display: flex; gap: 6px; align-items: center; font-size: 12px; padding: 8px 0; }
.update-conflict { display: flex; gap: 9px; align-items: start; margin: 12px 0; font-size: 12px; }
.update-conflict input { margin-top: 2px; accent-color: #222; }
.update-conflict small { display: block; color: #777; margin-top: 4px; }
.update-approve { background: #242424; color: white; margin-top: 8px; border: 1px solid #242424; }
.update-complete { display: flex; align-items: center; gap: 7px; font-size: 12px; padding: 13px; background: #ededed; border-radius: 8px; }
.update-disclosure { margin-top: 15px; border-top: 1px solid #e8e8e8; padding-top: 12px; font-size: 12px; }
.update-disclosure summary { cursor: pointer; color: #666; }
.update-disclosure textarea { width: 100%; min-height: 230px; resize: vertical; margin: 10px 0; padding: 10px; font-size: 11px; line-height: 1.6; color: #333; }
.update-disclosure pre { max-height: 300px; overflow: auto; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 11px; line-height: 1.7; color: #666; }
.update-disclosure a { display: inline-flex; gap: 5px; margin-top: 10px; color: #555; }
.update-disclosure button { padding: 8px 11px; font-size: 11px; }
.update-reject { display: flex; flex-wrap: wrap; gap: 8px; border-top: 1px solid #e6e6e6; margin-top: 18px; padding-top: 15px; }
.update-reject input { flex: 1; min-width: 120px; padding: 8px 10px; font-size: 11px; color: #555; }
.update-reject button { font-size: 11px; padding: 8px; }
.update-empty { display: flex; flex-direction: column; align-items: center; padding: 32px 18px; border: 1px dashed #ddd; border-radius: 10px; color: #999; text-align: center; }
.update-empty strong { margin-top: 13px; color: #555; font-size: 13px; }
.update-empty p { font-size: 12px; line-height: 1.8; max-width: 420px; }
.update-pagination { display: flex; align-items: center; justify-content: space-between; gap: 8px; color: #888; padding-top: 8px; }
.update-pagination small { font-size: 10px; }
.update-pagination button { padding: 6px; background: transparent; font-size: 10px; }
.update-message { font-size: 12px; line-height: 1.7; padding: 10px 12px; border-radius: 7px; background: #f4f4f4; }
.update-progress { display: flex; align-items: center; gap: 7px; color: #666; }
.update-record-error { font-size: 12px; color: #965315; background: #fff3e6; padding: 10px; border-radius: 7px; line-height: 1.7; }
.update-warnings { font-size: 11px; color: #888; line-height: 1.8; padding-left: 18px; }
.update-timing { display: grid; grid-template-columns: 1fr auto; gap: 7px; font-size: 11px; color: #777; }
.update-timing dd { margin: 0; font-variant-numeric: tabular-nums; }
.update-history { padding-left: 18px; }
.update-history li { padding: 6px 0; }
.update-history strong { display: block; font-size: 11px; }
.update-history small { display: block; color: #999; font-size: 10px; margin-top: 3px; }
@media(max-width: 700px) { .update-workspace.with-detail { grid-template-columns: 1fr; } .update-detail { padding: 15px; } .update-toolbar { gap: 10px; } .update-inbox { max-height: 350px; overflow: auto; } }
@media(prefers-reduced-motion: reduce) { .update-row { transition: none; } }
</style>
