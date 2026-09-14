<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { api, download, type Item } from '../api'
import { itemTypeLabels } from '../labels'
import { useRemoteItemSearch } from '../composables/useRemoteItemSearch'
const items = ref<Item[]>([]); const chosen = ref<number[]>([]); const result = ref<any>(null); const error = ref('')
const expandMaterials=ref(false)
watch(expandMaterials,()=>result.value=null)
const itemType = ref('machine'); const query = ref('')
const { searching, searchTotal, results: searchResults, search, cancel } = useRemoteItemSearch(items, value => { error.value = value })
const candidates = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  const source = term ? searchResults.value : items.value
  return source.filter(item => item.item_type === itemType.value && (!term || `${item.code} ${item.name} ${item.specification || ''}`.toLocaleLowerCase().includes(term))).slice(0, 200)
})
const selectedItems = computed(() => chosen.value.map(id => items.value.find(item => item.id === id)).filter(Boolean) as Item[])
async function loadType() { items.value = (await api<{ items: Item[] }>(`/items?item_type=${itemType.value}&limit=1000`)).items }
onMounted(loadType)
watch(query, value => { result.value = null; search(value, { item_type: itemType.value }) })
watch(itemType, async () => { cancel(); chosen.value = []; result.value = null; query.value = ''; await loadType() })
function toggle(id: number) { if (chosen.value.includes(id)) chosen.value = chosen.value.filter(value => value !== id); else if (chosen.value.length < 5) chosen.value.push(id) }
async function compare() { try { result.value = await api(`/compare?item_ids=${chosen.value.join(',')}&expand_materials=${expandMaterials.value}`) } catch (event) { error.value = (event as Error).message } }
</script>
<template><header class="page-head"><div><h1>BOM 矩阵比较</h1><p class="subtitle">筛选并选择 1–5 个同类型半成品、单元或整机，比较生产用原材料数量</p></div></header><div v-if="error" class="notice error">{{ error }}</div><section class="card"><div class="toolbar"><label>物料类型<select v-model="itemType"><option value="machine">整机</option><option value="unit">单元</option><option value="semi_finished">半成品</option></select></label><label>编码/名称/规格<input v-model="query" placeholder="输入后自动搜索全部物料，例如 00.999 或 水质" /></label><span class="subtitle">{{searching?'正在自动搜索…':query.trim()&&searchTotal>=0?`全库匹配 ${searchTotal} 条，显示 ${candidates.length} 条`:`显示 ${candidates.length} 条`}}，已选 {{ chosen.length }}/5</span></div><div class="chip-list"><span v-for="item in selectedItems" :key="item.id" class="chip">{{ item.code }}｜{{ item.name }}<button type="button" @click="toggle(item.id)">×</button></span></div><div class="table-wrap" style="max-height:300px"><table><thead><tr><th>选择</th><th>类型</th><th>编码</th><th>名称</th><th>规格</th></tr></thead><tbody><tr v-for="item in candidates" :key="item.id" class="clickable" @click="toggle(item.id)"><td><input type="checkbox" style="min-width:auto" :checked="chosen.includes(item.id)" :disabled="chosen.length>=5&&!chosen.includes(item.id)" @click.stop="toggle(item.id)" /></td><td>{{ itemTypeLabels[item.item_type] }}</td><td>{{ item.code }}</td><td>{{ item.name }}</td><td>{{ item.specification || '—' }}</td></tr></tbody></table></div><label><input v-model="expandMaterials" type="checkbox"/> 展开有下级组成的原材料</label><div class="actions"><button class="btn" :disabled="!chosen.length||chosen.length>5" @click="compare">开始比较</button><button v-if="result" class="btn secondary" @click="download(`/compare/export?item_ids=${chosen.join(',')}&expand_materials=${expandMaterials}`,'BOM差异比较.xlsx')">导出 Excel</button></div><div v-if="result" class="table-wrap"><table><thead><tr><th>原材料</th><th v-for="item in result.items" :key="item.id">{{ item.code }}</th><th>差异</th></tr></thead><tbody><tr v-for="row in result.rows" :key="row.item.id" :class="{'selected-row':row.different}"><td>{{ row.item.code }} {{ row.item.name }}</td><td v-for="item in result.items" :key="item.id">{{ row.values[String(item.id)] ?? '—' }}</td><td>{{ row.different ? '是' : '否' }}</td></tr></tbody></table></div></section></template>
