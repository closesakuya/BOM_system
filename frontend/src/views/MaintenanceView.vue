<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { api, apiWithImpactConfirmation, type Item } from '../api'
import ItemAutocomplete from '../components/ItemAutocomplete.vue'
import { useRemoteItemSearch } from '../composables/useRemoteItemSearch'
import { itemTypeLabels } from '../labels'

const items = ref<Item[]>([]); const candidateParents = ref<Item[]>([]); const preview = ref<any>(null)
const message = ref(''); const error = ref(''); const candidateMessage = ref('请先选择物料'); const loadingParents = ref(false)
const { searching: itemSearching, searchTotal: itemSearchTotal, search: searchItems, cancel: cancelItemSearch } = useRemoteItemSearch(items, value => { error.value = value })
const parentDraft = ref(0); const sourceType = ref(''); const targetType = ref(''); const parentType = ref('')
let candidateRequest = 0
const form = reactive<any>({ operation: 'replace', source_item_id: 0, target_item_id: 0, parent_item_ids: [] as number[], quantity: '1', reason: '批量维护 BOM' })

const sourceCandidates = computed(() => items.value.filter(item => !sourceType.value || item.item_type === sourceType.value))
const targetCandidates = computed(() => items.value.filter(item => !targetType.value || item.item_type === targetType.value))
const parentCandidates = computed(() => candidateParents.value.filter(item => !parentType.value || item.item_type === parentType.value))
const parentTypes = computed(() => [...new Set(candidateParents.value.map(item => item.item_type))])
const selectedParents = computed(() => form.parent_item_ids.map((id: number) => items.value.find(item => item.id === id)).filter(Boolean) as Item[])
const needsSource = computed(() => form.operation !== 'add')
const needsTarget = computed(() => ['replace', 'add'].includes(form.operation))
const sourceLabel = computed(() => form.operation === 'delete' ? '待删除子物料' : form.operation === 'adjust' ? '待调量子物料' : '原物料')
const targetLabel = computed(() => form.operation === 'add' ? '要新增的子物料' : '替换后的目标物料')
const operationHelpMap: Record<string, string> = {
  replace: '在所选父项中，把直接包含的原物料替换为目标物料，原数量不变；父项只列出直接包含原物料且允许目标物料层级的对象。',
  adjust: '统一修改所选父项中该子物料的数量；父项只列出直接包含该物料的对象。',
  add: '给所选父项新增目标子物料；父项只列出层级合法且不会形成环路的对象。若组成已存在，数量会累加。',
  delete: '从所选父项的直接 BOM 中删除该子物料；不会删除物料档案，操作会写入变更记录。',
}
const operationHelp = computed(() => operationHelpMap[form.operation])
const readyToPreview = computed(() => form.parent_item_ids.length && (!needsSource.value || form.source_item_id) && (!needsTarget.value || form.target_item_id) && (!['add', 'adjust'].includes(form.operation) || Number(form.quantity) > 0))

onMounted(async () => { items.value = (await api<{ items: Item[] }>('/items?limit=1000')).items })
watch(() => form.operation, () => {
  form.source_item_id = 0; form.target_item_id = 0; form.parent_item_ids = []; parentDraft.value = 0
  sourceType.value = ''; targetType.value = ''; parentType.value = ''; candidateParents.value = []; preview.value = null
  candidateMessage.value = form.operation === 'add' ? '请先选择要新增的子物料' : '请先选择原物料'
})
watch([() => form.source_item_id, () => form.target_item_id], loadParentCandidates)
watch(sourceType, () => { cancelItemSearch(); if (form.source_item_id && !sourceCandidates.value.some(item => item.id === form.source_item_id)) form.source_item_id = 0 })
watch(targetType, () => { cancelItemSearch(); if (form.target_item_id && !targetCandidates.value.some(item => item.id === form.target_item_id)) form.target_item_id = 0 })
watch(parentType, () => { form.parent_item_ids = form.parent_item_ids.filter((id: number) => parentCandidates.value.some(item => item.id === id)); parentDraft.value = 0; preview.value = null })

async function loadParentCandidates() {
  const requestId = ++candidateRequest
  preview.value = null; form.parent_item_ids = []; parentDraft.value = 0; parentType.value = ''; candidateParents.value = []
  if (needsSource.value && !form.source_item_id) { candidateMessage.value = '请先选择原物料'; return }
  if (form.operation === 'add' && !form.target_item_id) { candidateMessage.value = '请先选择要新增的子物料'; return }
  loadingParents.value = true
  try {
    const params = new URLSearchParams({ operation: form.operation })
    if (form.source_item_id) params.set('source_item_id', String(form.source_item_id))
    if (form.target_item_id) params.set('target_item_id', String(form.target_item_id))
    const result = await api<{ items: Item[]; message: string }>(`/maintenance/parent-candidates?${params}`)
    if (requestId !== candidateRequest) return
    candidateParents.value = result.items; candidateMessage.value = result.message
    items.value = [...new Map([...items.value, ...result.items].map(item => [item.id, item])).values()]
  } catch (event) { if (requestId === candidateRequest) error.value = (event as Error).message } finally { if (requestId === candidateRequest) loadingParents.value = false }
}
function searchSourceCandidates(query: string) { searchItems(query, { item_type: sourceType.value || undefined }) }
function searchTargetCandidates(query: string) { searchItems(query, { item_type: targetType.value || undefined }) }
function addParent() { if (parentDraft.value && !form.parent_item_ids.includes(parentDraft.value)) form.parent_item_ids.push(parentDraft.value); parentDraft.value = 0; preview.value = null }
function removeParent(id: number) { form.parent_item_ids = form.parent_item_ids.filter((value: number) => value !== id); preview.value = null }
function itemById(id: number) { return items.value.find(item => item.id === id) }
async function runPreview() {
  error.value = ''; message.value = ''
  try { preview.value = await api('/maintenance/preview', { method: 'POST', body: JSON.stringify({ ...form, source_item_id: form.source_item_id || null, target_item_id: form.target_item_id || null, quantity: ['add', 'adjust'].includes(form.operation) ? form.quantity : null }) }) }
  catch (event) { error.value = (event as Error).message }
}
async function apply() {
  const verb = form.operation === 'delete' ? '删除' : '修改'
  if (!confirm(`确认${verb} ${preview.value?.affected_count || 0} 条 BOM 组成？此操作会写入变更记录。`)) return
  try { const result = await apiWithImpactConfirmation<any>('/maintenance/apply', { method: 'POST', body: JSON.stringify({ ...form, source_item_id: form.source_item_id || null, target_item_id: form.target_item_id || null, quantity: ['add', 'adjust'].includes(form.operation) ? form.quantity : null }) }); message.value = `批量操作完成，共处理 ${result.changed} 条；可在物料的“变更记录”中追溯。`; preview.value = null; await loadParentCandidates() }
  catch (event) { error.value = (event as Error).message }
}
</script>

<template>
  <header class="page-head"><div><h1>BOM 批量维护</h1><p class="subtitle">按基础组成关系和合法层级批量维护；路径选用项请在所属物料 BOM 中配置。替换或删除影响专属选配时会列出清除范围，确认后才提交。</p></div></header>
  <div v-if="error" class="notice error">{{ error }}</div><div v-if="message" class="notice">{{ message }}</div>
  <div class="steps"><div class="step"><strong>选择操作和子物料</strong><br><span class="subtitle">先选层级，再输入编码、名称或规格；也可输入完整编码直接选中。</span></div><div class="step"><strong>从有效候选中加入父项</strong><br><span class="subtitle">系统按直接引用或合法 BOM 层级自动限制候选，父项同样支持层级筛选与搜索。</span></div><div class="step"><strong>预览实际变化后确认</strong><br><span class="subtitle">新增会显示新数量，删除会明确标识待删除关系；确认后记录操作人与原因。</span></div></div>
  <div class="grid grid-2"><section class="card"><h2>操作参数</h2><div class="form-grid">
    <label>业务操作<select v-model="form.operation"><option value="replace">替换组成</option><option value="adjust">调整组成数量</option><option value="add">新增组成</option><option value="delete">删除组成</option></select></label><div class="notice" style="margin:0">{{ operationHelp }}</div>
    <template v-if="needsSource"><label>{{ sourceLabel }}层级<select v-model="sourceType"><option value="">全部层级</option><option v-for="(label,value) in itemTypeLabels" :key="value" :value="value">{{ label }}</option></select></label><ItemAutocomplete v-model="form.source_item_id" :items="sourceCandidates" :searching="itemSearching" :search-total="itemSearchTotal" :label="sourceLabel" placeholder="输入编码、名称或规格，自动搜索全部物料" @search="searchSourceCandidates" /></template>
    <template v-if="needsTarget"><label>{{ targetLabel }}层级<select v-model="targetType"><option value="">全部层级</option><option v-for="(label,value) in itemTypeLabels" :key="value" :value="value">{{ label }}</option></select></label><ItemAutocomplete v-model="form.target_item_id" :items="targetCandidates" :searching="itemSearching" :search-total="itemSearchTotal" :label="targetLabel" placeholder="输入编码、名称或规格，自动搜索全部物料" @search="searchTargetCandidates" /></template>
    <label v-if="['adjust','add'].includes(form.operation)">{{ form.operation==='add'?'新增数量':'调整后数量' }}<input v-model="form.quantity" type="number" min="0.000001" step="any" /></label>
    <div class="span-2 card" style="padding:14px"><div class="toolbar"><label>父项层级<select v-model="parentType" :disabled="!candidateParents.length"><option value="">全部合法层级</option><option v-for="value in parentTypes" :key="value" :value="value">{{ itemTypeLabels[value] }}</option></select></label><ItemAutocomplete v-model="parentDraft" :items="parentCandidates" label="添加父项" placeholder="搜索或输入父项完整编码" /><button class="btn secondary" type="button" :disabled="!parentDraft" @click="addParent">加入父项</button></div><p class="subtitle">{{ loadingParents ? '正在读取 BOM 引用关系…' : candidateMessage }}；当前层级可选 {{ parentCandidates.length }} 个。请逐个加入需要维护的父项。</p><div class="chip-list"><span v-for="item in selectedParents" :key="item.id" class="chip">{{ item.code }}｜{{ item.name }}（{{ itemTypeLabels[item.item_type] }}）<button type="button" aria-label="移除父项" @click="removeParent(item.id)">×</button></span></div><div v-if="!selectedParents.length" class="empty" style="padding:14px">尚未加入父项</div></div>
    <label class="span-2">变更原因<input v-model="form.reason" required placeholder="例如：元件停产，统一替换；或设计变更，删除旧组成" /></label>
  </div><div class="actions"><button class="btn" :disabled="!readyToPreview" @click="runPreview">预览实际变化</button></div></section>
  <section class="card"><h2>影响预览</h2><div v-if="!preview" class="empty">完成左侧选择后点击“预览实际变化”，此时不会修改数据</div><template v-else><div class="notice">预计处理 {{ preview.affected_count }} 条直接 BOM 组成</div><div class="table-wrap"><table><thead><tr><th>父项</th><th>子物料</th><th>{{ form.operation==='add'?'变化':'当前数量' }}</th><th>结果</th></tr></thead><tbody><tr v-for="(line,index) in preview.lines" :key="line.id||index"><template v-if="form.operation==='add'"><td>{{ line.parent.code }}｜{{ line.parent.name }}</td><td>{{ line.child.code }}｜{{ line.child.name }}</td><td>{{ line.before_quantity }} → {{ line.after_quantity }}</td><td>{{ line.effect==='merge'?'已有组成，数量累加':'新增组成' }}</td></template><template v-else><td>{{ itemById(line.parent_item_id)?.code }}｜{{ itemById(line.parent_item_id)?.name }}</td><td>{{ line.child.code }}｜{{ line.child.name }}</td><td>{{ line.quantity }}</td><td>{{ form.operation==='delete'?'删除该组成':form.operation==='replace'?'替换为目标物料':'修改为新数量' }}</td></template></tr></tbody></table></div><div v-if="!preview.affected_count" class="notice error">没有实际匹配项，请重新检查物料和父项。</div><div class="actions"><button class="btn danger" :disabled="!preview.affected_count" @click="apply">确认{{ form.operation==='delete'?'删除':'执行' }}并记录变更</button></div></template></section></div>
</template>
