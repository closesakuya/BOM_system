<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { Item } from '../api'
import { displayLabel } from '../labels'

const props = withDefaults(defineProps<{
  modelValue: number | null | undefined
  items: Item[]
  label?: string
  placeholder?: string
  disabled?: boolean
  clearable?: boolean
  hasMore?: boolean
  loadingMore?: boolean
  loadedItems?: number
  totalItems?: number
  searching?: boolean
  searchTotal?: number
  enterSelect?: boolean
}>(), { label: '物料', placeholder: '输入编码、名称或规格搜索', disabled: false, clearable: false, hasMore: false, loadingMore: false, loadedItems: -1, totalItems: 0, searching: false, searchTotal: -1, enterSelect: true })
const emit = defineEmits<{ 'update:modelValue': [value: number]; 'load-more': []; 'search': [query: string]; 'submit': [query: string] }>()
const query = ref('')
const inputRef = ref<HTMLInputElement | null>(null)
const open = ref(false)
const activeIndex = ref(0)
const displayLimit = ref(80)
let closeTimer: number | undefined

const selected = computed(() => props.items.find(item => item.id === props.modelValue))
const matches = computed(() => {
  const term = query.value.trim().toLocaleLowerCase()
  if (!term) return [...props.items].sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
  const rank = (item: Item) => {
    const code = item.code.toLocaleLowerCase(); const name = item.name.toLocaleLowerCase(); const specification = (item.specification || '').toLocaleLowerCase()
    if (code === term) return 0
    if (code.startsWith(term)) return 1
    if (code.includes(term)) return 2
    if (name.startsWith(term)) return 3
    if (name.includes(term)) return 4
    if (specification.includes(term)) return 5
    return 99
  }
  return props.items.filter(item => rank(item) < 99).sort((left, right) => rank(left) - rank(right) || left.code.localeCompare(right.code, 'zh-CN'))
})
const candidates = computed(() => matches.value.slice(0, displayLimit.value))

watch(() => props.modelValue, () => {
  if (selected.value) query.value = `${selected.value.code}｜${selected.value.name}`
  else if (!open.value) query.value = ''
}, { immediate: true })
watch(() => props.items, () => {
  if (!open.value || props.modelValue || !query.value.trim()) return
  const exact = props.items.find(item => item.code === query.value.trim() || item.name === query.value.trim())
  if (exact) choose(exact)
})

function input() {
  if (closeTimer) window.clearTimeout(closeTimer)
  open.value = true
  activeIndex.value = 0
  displayLimit.value = 80
  emit('search', query.value.trim())
  const exact = props.items.find(item => item.code === query.value.trim() || item.name === query.value.trim())
  if (exact) { choose(exact); return }
  emit('update:modelValue', 0)
}
function choose(item: Item) {
  if (closeTimer) window.clearTimeout(closeTimer)
  query.value = `${item.code}｜${item.name}`
  emit('update:modelValue', item.id)
  open.value = false
}
async function clearSelection() {
  if (closeTimer) window.clearTimeout(closeTimer)
  query.value = ''
  activeIndex.value = 0
  displayLimit.value = 80
  open.value = true
  emit('update:modelValue', 0)
  emit('search', '')
  await nextTick()
  inputRef.value?.focus()
}
function focusInput() {
  if (closeTimer) window.clearTimeout(closeTimer)
  open.value = true; activeIndex.value = 0
}
function closeLater() { closeTimer = window.setTimeout(() => { open.value = false; closeTimer = undefined }, 160) }
function showMoreCandidates() { displayLimit.value += 80 }
function loadMoreItems() { emit('load-more') }
function keydown(event: KeyboardEvent) {
  if (event.key === 'Escape') { open.value = false; return }
  if (!open.value) open.value = true
  if (event.key === 'ArrowDown') {
    event.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, Math.max(0, candidates.value.length - 1))
  } else if (event.key === 'ArrowUp') {
    event.preventDefault()
    activeIndex.value = Math.max(0, activeIndex.value - 1)
  } else if (event.key === 'Enter' && !props.enterSelect) {
    event.preventDefault()
    open.value = false
    emit('submit', query.value.trim())
  } else if (event.key === 'Enter' && candidates.value.length) {
    event.preventDefault()
    choose(candidates.value[activeIndex.value] || candidates.value[0])
  }
}
onBeforeUnmount(() => { if (closeTimer) window.clearTimeout(closeTimer) })
</script>

<template>
  <label class="item-combobox">{{ label }}
    <span class="item-combobox-input"><input ref="inputRef" v-model="query" :placeholder="placeholder" :disabled="disabled" autocomplete="off" aria-autocomplete="list" :aria-expanded="open" @input="input" @focus="focusInput" @keydown="keydown" @blur="closeLater" /><button v-if="clearable&&!disabled&&(query||modelValue)" type="button" class="combobox-clear" :aria-label="`清除${label}`" title="清除后重新选择" @mousedown.prevent @click="clearSelection">×</button></span>
    <div v-if="open && !disabled" class="suggestions" role="listbox">
      <button v-for="(item,index) in candidates" :key="item.id" type="button" role="option" :aria-selected="index===activeIndex" :class="{active:index===activeIndex}" @mousemove="activeIndex=index" @mousedown.prevent="choose(item)">
        <strong>{{ item.code }}</strong><span>{{ item.name }}</span><small>{{ item.specification || '无规格' }}｜{{ displayLabel(item.source_type || item.status || item.item_type) }}</small>
      </button>
      <div v-if="!candidates.length" class="suggestion-empty">{{searching?'正在自动搜索全部物料…':query.trim()&&searchTotal===0?'全部物料中没有匹配项，请调整编码、名称或规格':loadingMore?'正在加载候选物料…':hasMore?'当前已加载数据中没有匹配项，系统会自动搜索全部物料':'没有匹配物料，请调整编码或名称'}}</div>
      <div class="suggestion-summary"><span><template v-if="query.trim()&&searchTotal>=0">全库匹配 {{searchTotal}} 条；</template>当前匹配 {{ matches.length }} 条，已显示 {{ candidates.length }} 条<span v-if="totalItems">；浏览数据 {{loadedItems>=0?loadedItems:items.length}} / {{totalItems}} 条</span><span v-if="searching">；正在自动搜索…</span></span><span v-if="candidates.length<matches.length||hasMore" class="suggestion-actions"><button v-if="candidates.length<matches.length" type="button" @mousedown.prevent @click="showMoreCandidates">显示更多候选（剩余 {{matches.length-candidates.length}} 条）</button><button v-if="hasMore&&!query.trim()" type="button" :disabled="loadingMore" @mousedown.prevent @click="loadMoreItems">{{loadingMore?'正在加载…':'继续加载剩余物料'}}</button></span><span v-else-if="totalItems&&!query.trim()" class="suggestion-complete">候选数据已全部加载</span></div>
    </div>
  </label>
</template>
