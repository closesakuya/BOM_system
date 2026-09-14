<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, apiWithImpactConfirmation, download, session, type Item } from '../api'
import ItemAutocomplete from '../components/ItemAutocomplete.vue'
import ItemQuickViewModal from '../components/ItemQuickViewModal.vue'
import PathAlternativeEditor from '../components/PathAlternativeEditor.vue'
const pathEditor = ref<any>(null)
const focusedBomPath = ref('')
async function pathSaved() { pathEditor.value=null; if(selected.value) await choose(selected.value); tab.value='bom' }
import { useRemoteItemSearch } from '../composables/useRemoteItemSearch'
import { actionLabels, displayLabel, entityLabels, itemTypeLabels } from '../labels'

type Rule = { id: number; item_type: string; large_category?: string; small_category?: string; material_attribute?: string; prefix: string; pattern: string; active: boolean }
type BomLine = { id: number; child_item_id: number; quantity: string; sort_order: number; line_remark?: string; alternative_group_id?: number; child: Item }
type TreeRow = { sequence: number; level: number; path: number[]; line_path: number[]; configuration_owner?: Item; local_configuration?: boolean; configuration_mode?: string; parent_item_id: number; line_id: number; quantity: string; line_remark?: string; item: Item; disabled_warning: boolean; latest_change_reason?: string; is_alternative?: boolean; is_backup_path?: boolean; alternative_group_name?: string; market_share?: string }
type CodeAvailability = {
  valid: boolean; code: string; exists: boolean; message: string
  conflict_item?: Item; maximum?: Item; same_body_maximum?: Item
  duplicate_items?: Item[]; next_body_code?: string; next_version_code?: string
}
type KeyCodeCheck = { valid: boolean; normalized?: string; message: string; duplicate_items?: Item[] }
type ItemPage = { total: number; items: Item[] }
type CategoryOption = { value: string; code: string }

const ITEM_PAGE_SIZE = 1000
const ITEM_UPDATED_STORAGE_KEY = 'bom_item_updated'

const route = useRoute()
const router = useRouter()
const type = computed(() => String(route.params.type))
const labels = itemTypeLabels
const items = ref<Item[]>([]); const allItems = ref<Item[]>([]); const rules = ref<Rule[]>([])
const batchSelected = ref<number[]>([]); const showDeleted = ref(false)
const listFilter = ref(''); const materialStatusFilter=ref(''); const componentFilter=ref('')
const listQuery = ref(''); const formalFilter = ref(''); const modelFilter = ref(''); const semiKindFilter = ref('')
const machineModels = ref<string[]>([]); const keyComponentCodes = ref<string[]>([])
const selected = ref<Item | null>(null); const detail = ref<any>(null); const tab = ref('basic')
const searchItemId = ref(0); const loading = ref(false); const error = ref(''); const message = ref(''); const showCreate = ref(false)
const showEditReason = ref(false); const editSaving = ref(false)
const itemTotal = ref(0); const listLoadedCount = ref(0); const listLoadingMore = ref(false)
const allItemsTotal = ref(0); const candidateLoadedCount = ref(0); const candidateLoadingMore = ref(false)
const copySourceId = ref(0); const copyBusy = ref(false)
const { searching: candidateSearching, searchTotal: candidateSearchTotal, search: searchCandidateItems, cancel: cancelCandidateSearch } = useRemoteItemSearch(allItems, value => { error.value = value })
const codeCheck = ref<CodeAvailability | null>(null); const codeChecking = ref(false); const keyCodeCheck = ref<KeyCodeCheck | null>(null)
const tree = ref<TreeRow[]>([]); const production = ref<any[]>([]); const references = ref<any[]>([]); const history = ref<any[]>([])
const referenceFilter = ref<'all' | 'direct' | 'indirect'>('all')
const collapsedPaths = ref(new Set<string>())
const lineQuantities = reactive<Record<number, string>>({})
const bomBusy = ref(false); const savingLineId = ref(0); const batchBusy = ref(false)
const replaceLine = ref<BomLine | null>(null); const replaceBusy = ref(false)
const replaceForm = reactive({ child_item_id: 0, reason: '替换 BOM 组成' })
const technicalDetailed = ref(false); const productionDetailed = ref(false)
const technicalShowAlternatives = ref(sessionStorage.getItem('bom_switch_technical_alternatives') !== 'false')
const technicalExpandMaterials = ref(sessionStorage.getItem('bom_switch_technical_materials') === 'true')
const productionShowAlternatives = ref(sessionStorage.getItem('bom_switch_production_alternatives') !== 'false')
const productionExpandMaterials = ref(sessionStorage.getItem('bom_switch_production_materials') === 'true')
const quickViewItem = ref<any | null>(null); const quickViewLoading = ref(false); const quickViewError = ref('')
const showPromote = ref(false); const promoteBusy = ref(false); const promoteChecking = ref(false)
const promoteCheck = ref<CodeAvailability | null>(null)
const promoteForm = reactive<any>({ code: '', auxiliary_code: '', name: '', specification: '', source_type: 'purchased', unit: 'pcs', remark: '', previous_version_name: '', invoice_name: '', material_attribute: '', key_component_code: '', similarity_confirmed: false, reason: '' })
const promoteGuide = reactive({ large: '', small: '', ruleId: 0 })
const unofficialEstimate = ref('')
const splitRef = ref<HTMLElement | null>(null)
const listTableScrollRef = ref<HTMLElement | null>(null)
const storedListPaneWidth = Number(localStorage.getItem('bom_item_list_pane_width'))
const listPaneWidth = ref(Number.isFinite(storedListPaneWidth) && storedListPaneWidth >= 360 ? storedListPaneWidth : 560)
const resizingPanes = ref(false)
let resizeStartX = 0
let resizeStartWidth = 0
let loadedListItemIds = new Set<number>()
let injectedListItemId = 0
let revealSelectedItemId = 0
let codeCheckTimer: number | undefined
let keyCodeTimer: number | undefined
let codeCheckRequest = 0
let quickViewRequest = 0
let promoteCheckTimer: number | undefined
let externalDetailOpened = false
let externalDetailBlurred = false
const form = reactive<any>({ code: '', auxiliary_code: '', name: '', specification: '', source_type: 'purchased', unit: 'pcs', status: 'trial', remark: '', previous_version_name: '', invoice_name: '', material_attribute: '', key_component_code: '', machine_model: '', is_formally_imported: true, reason: '新建物料', similarity_confirmed: false, components: [] })
const guide = reactive({ large: '', small: '', ruleId: 0 })
const componentDraft = reactive({ child_item_id: 0, quantity: '1', sort_order: 1, line_remark: '' })
const bomDraft = reactive({ child_item_id: 0, quantity: '1', line_remark: '', reason: '新增 BOM 组成' })
const edit = reactive<any>({ name: '', specification: '', unit: '', status: '', source_type: '', remark: '', previous_version_name: '', invoice_name: '', material_attribute: '', key_component_code: '', machine_model: '', reason: '', similarity_confirmed: true })
const canWrite = computed(() => ['admin', 'maintainer'].includes(session.user?.role || ''))
const canDelete = computed(() => session.user?.role === 'admin')
const canModifyDetail = computed(() => canWrite.value && detail.value?.unofficial_status !== 'archived')
const hasMoreListItems = computed(() => listLoadedCount.value < itemTotal.value)
const hasMoreCandidateItems = computed(() => candidateLoadedCount.value < allItemsTotal.value)
const copyCandidates = computed(() => allItems.value.filter(item => item.item_type === type.value && !item.deleted_at && item.unofficial_status !== 'archived'))
const listSearchCandidates = computed(() => {
  const rows = [...allItems.value, ...items.value]
  return [...new Map(rows.filter(item => item.item_type === type.value && (showDeleted.value || !item.deleted_at) && matchesListFilter(item)).map(item => [item.id, item])).values()]
})
const largeCategories = computed<CategoryOption[]>(() => {
  const options = new Map<string, Set<string>>()
  rules.value.filter(rule => rule.active && rule.item_type === type.value && rule.large_category).forEach(rule => {
    const codes = options.get(rule.large_category!) || new Set<string>()
    codes.add(rule.prefix.split('.')[0])
    options.set(rule.large_category!, codes)
  })
  return [...options].map(([value, codes]) => ({ value, code: [...codes].join('、') }))
})
const smallCategories = computed<CategoryOption[]>(() => {
  const options = new Map<string, Set<string>>()
  rules.value.filter(rule => rule.active && rule.item_type === type.value && (!guide.large || rule.large_category === guide.large) && rule.small_category).forEach(rule => {
    const codes = options.get(rule.small_category!) || new Set<string>()
    codes.add(rule.prefix.replace(/\.$/, ''))
    options.set(rule.small_category!, codes)
  })
  return [...options].map(([value, codes]) => ({ value, code: [...codes].join('、') }))
})
const filteredRules = computed(() => rules.value.filter(r => r.active && r.item_type === type.value && (!guide.large || r.large_category === guide.large) && (!guide.small || r.small_category === guide.small)))
const promoteLargeCategories = computed(() => largeCategories.value)
const promoteSmallCategories = computed(() => {
  const options = new Map<string, Set<string>>()
  rules.value.filter(rule => rule.active && rule.item_type === 'material' && (!promoteGuide.large || rule.large_category === promoteGuide.large) && rule.small_category).forEach(rule => {
    const codes = options.get(rule.small_category!) || new Set<string>(); codes.add(rule.prefix.replace(/\.$/, '')); options.set(rule.small_category!, codes)
  })
  return [...options].map(([value, codes]) => ({ value, code: [...codes].join('、') }))
})
const promoteRules = computed(() => rules.value.filter(r => r.active && r.item_type === 'material' && (!promoteGuide.large || r.large_category === promoteGuide.large) && (!promoteGuide.small || r.small_category === promoteGuide.small)))
const selectedCodeRule = computed(() => rules.value.find(rule => rule.id === guide.ruleId))
const selectedRuleTemplate = computed(() => selectedCodeRule.value?.pattern.match(/[0-9X.]+/i)?.[0] || selectedCodeRule.value?.prefix || '')
const selectedRulePrefix = computed(() => {
  const template = selectedRuleTemplate.value
  const marker = template.toUpperCase().indexOf('X')
  return marker >= 0 ? template.slice(0, marker) : selectedCodeRule.value?.prefix || ''
})
const selectedRuleSuffix = computed({
  get: () => selectedCodeRule.value && form.code.startsWith(selectedRulePrefix.value)
    ? form.code.slice(selectedRulePrefix.value.length)
    : '',
  set: (value: string) => { form.code = `${selectedRulePrefix.value}${String(value || '').replace(/[^0-9.]/g, '')}` },
})
const selectedRuleSuffixPlaceholder = computed(() => selectedRuleTemplate.value.slice(selectedRulePrefix.value.length).replace(/X/gi, '0'))
const allowedChildren = computed(() => {
  const allowed: Record<string, string[]> = { material: ['material'], semi_finished: ['semi_finished', 'material'], unit: ['semi_finished', 'material'], machine: ['unit', 'semi_finished', 'material'] }
  return allItems.value.filter(row => allowed[type.value]?.includes(row.item_type) && row.id !== selected.value?.id && row.status !== 'disabled' && row.is_formally_imported !== false)
})
const createAllowedChildren = computed(() => {
  const allowed: Record<string, string[]> = { material: ['material'], semi_finished: ['semi_finished', 'material'], unit: ['semi_finished', 'material'], machine: ['unit', 'semi_finished', 'material'] }
  return allItems.value.filter(row => allowed[type.value]?.includes(row.item_type) && row.status !== 'disabled' && row.is_formally_imported !== false)
})
const replaceTarget = computed(() => allItems.value.find(row => row.id === replaceForm.child_item_id))
const visibleTree = computed(() => tree.value.filter(row => {
  for (let length = 2; length < row.path.length; length += 1) {
    if (collapsedPaths.value.has(row.path.slice(0, length).join('-'))) return false
  }
  return true
}))
const filteredReferences = computed(() => references.value.filter(row =>
  referenceFilter.value === 'all'
  || (referenceFilter.value === 'direct' ? row.is_direct : !row.is_direct),
))
const technicalLevelLabels = computed(() => {
  const lastChildByParent = new Map<string, string>()
  for (const row of tree.value) {
    const path = row.path.join('-')
    lastChildByParent.set(row.path.slice(0, -1).join('-'), path)
  }
  return new Map(tree.value.map(row => {
    const path = row.path.join('-')
    const prefix: string[] = []
    for (let ancestorLevel = 1; ancestorLevel < row.level; ancestorLevel += 1) {
      const ancestorPath = row.path.slice(0, ancestorLevel + 1)
      const ancestorKey = ancestorPath.join('-')
      const ancestorParentKey = ancestorPath.slice(0, -1).join('-')
      prefix.push(lastChildByParent.get(ancestorParentKey) === ancestorKey ? '   ' : '│  ')
    }
    const isLast = lastChildByParent.get(row.path.slice(0, -1).join('-')) === path
    return [path, `${prefix.join('')}${isLast ? '└─' : '├─'} ${row.level}级`]
  }))
})
const quickViewHref = computed(() => quickViewItem.value
  ? router.resolve({ path: `/items/${quickViewItem.value.item_type}`, query: { id: String(quickViewItem.value.id), locate: '1' } }).href
  : '#')
const fieldLabels: Record<string, string> = {
  name: '名称', specification: '规格型号', unit: '单位', status: '状态', source_type: '来源',
  remark: '备注', previous_version_name: '上一版本名称', invoice_name: '发票名称',
  material_attribute: '材料属性', key_component_code: '关键器件码', historical_item_code: '历史物料号', unofficial_status: '封存状态', machine_model: '机型', is_formally_imported: '正式导入状态', quantity: '数量', child_item_id: '子物料',
  component: '组件', line_remark: 'BOM 行备注', alternative_group_id: '替代组', requires_assembly: '需要组装', deleted_at: '删除状态',
}
const historyScopeLabels: Record<string, string> = { self: '本物料', direct_component: '本物料组成', descendant: '下级组成' }

function resetForm() {
  form.copy_source_id=null
  Object.assign(form, { code: '', auxiliary_code: '', name: '', specification: '', source_type: 'purchased', unit: 'pcs', status: 'trial', remark: '', previous_version_name: '', invoice_name: '', material_attribute: '', key_component_code: '', machine_model: '', is_formally_imported: true, reason: '新建物料', similarity_confirmed: false, components: [] })
  Object.assign(guide, { large: '', small: '', ruleId: 0 })
  Object.assign(componentDraft, { child_item_id: 0, quantity: '1', sort_order: 1, line_remark: '' })
  copySourceId.value = 0; codeCheck.value = null; codeChecking.value = false; keyCodeCheck.value = null; unofficialEstimate.value = ''
  codeCheckRequest += 1
  if (codeCheckTimer) window.clearTimeout(codeCheckTimer)
}
function clampListPaneWidth(width: number) {
  const containerWidth = splitRef.value?.getBoundingClientRect().width || 1000
  const maximum = Math.max(360, containerWidth - 442)
  return Math.round(Math.min(Math.max(width, 360), maximum))
}
function persistListPaneWidth() {
  localStorage.setItem('bom_item_list_pane_width', String(listPaneWidth.value))
}
function startPaneResize(event: PointerEvent) {
  if (window.matchMedia('(max-width: 1250px)').matches || !splitRef.value) return
  resizeStartX = event.clientX
  resizeStartWidth = splitRef.value.firstElementChild?.getBoundingClientRect().width || listPaneWidth.value
  resizingPanes.value = true
  document.body.classList.add('split-resizing')
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  event.preventDefault()
}
function movePaneResize(event: PointerEvent) {
  if (!resizingPanes.value) return
  listPaneWidth.value = clampListPaneWidth(resizeStartWidth + event.clientX - resizeStartX)
}
function stopPaneResize(event: PointerEvent) {
  if (!resizingPanes.value) return
  resizingPanes.value = false
  document.body.classList.remove('split-resizing')
  const handle = event.currentTarget as HTMLElement
  if (handle.hasPointerCapture(event.pointerId)) handle.releasePointerCapture(event.pointerId)
  persistListPaneWidth()
}
function resizePanesByKeyboard(event: KeyboardEvent) {
  const delta = event.key === 'ArrowLeft' ? -24 : event.key === 'ArrowRight' ? 24 : 0
  if (!delta) return
  event.preventDefault()
  listPaneWidth.value = clampListPaneWidth(listPaneWidth.value + delta)
  persistListPaneWidth()
}
function resetPaneWidth() {
  const containerWidth = splitRef.value?.getBoundingClientRect().width || 1080
  listPaneWidth.value = clampListPaneWidth(containerWidth * .52)
  persistListPaneWidth()
}
function ensureItemInList(item: Item) {
  if (injectedListItemId && injectedListItemId !== item.id && !loadedListItemIds.has(injectedListItemId)) {
    items.value = items.value.filter(row => row.id !== injectedListItemId)
    injectedListItemId = 0
  }
  if (items.value.some(row => row.id === item.id)) return
  items.value = [...items.value, item].sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
  injectedListItemId = item.id
}
function matchesListFilter(item: Item, itemType = type.value, filter = listFilter.value) {
  if (!showDeleted.value && !filter && !materialStatusFilter.value && item.status==='disabled') return false
  if (itemType==='material' && materialStatusFilter.value && item.status!==materialStatusFilter.value) return false
  if (itemType==='material' && componentFilter.value && String(item.requires_assembly)!==componentFilter.value) return false
  if (filter && (itemType === 'material' ? item.source_type !== filter : item.status !== filter)) return false
  if (itemType === 'material' && formalFilter.value === 'official' && !item.is_formally_imported) return false
  if (itemType === 'material' && ['pending','archived'].includes(formalFilter.value) && item.unofficial_status !== formalFilter.value) return false
  if (itemType === 'machine' && modelFilter.value && item.machine_model !== modelFilter.value) return false
  if (itemType === 'semi_finished' && semiKindFilter.value && (item.is_combination ? 'combination' : 'normal') !== semiKindFilter.value) return false
  const query = listQuery.value.trim().toLocaleLowerCase()
  if (!query) return true
  return [item.code, item.historical_item_code || '', item.name, item.specification || '', item.key_component_code || ''].some(value => value.toLocaleLowerCase().includes(query))
}
function listStateKey() { return JSON.stringify([type.value, materialStatusFilter.value, componentFilter.value, showDeleted.value, listFilter.value, formalFilter.value, modelFilter.value, semiKindFilter.value, listQuery.value]) }
function listRequestPath(itemType: string, includeDeleted: boolean, filter: string, offset = 0, limit = ITEM_PAGE_SIZE) {
  const params = new URLSearchParams({
    item_type: itemType,
    include_disabled: String(includeDeleted),
    limit: String(limit),
  })
  if (offset) params.set('offset', String(offset))
  if (itemType==='material'&&materialStatusFilter.value) params.set('status',materialStatusFilter.value)
  if (itemType==='material'&&componentFilter.value) params.set('has_components',componentFilter.value)
  if (filter) params.set(itemType === 'material' ? 'source_type' : 'status', filter)
  if (listQuery.value.trim()) params.set('q', listQuery.value.trim())
  if (itemType === 'material' && formalFilter.value === 'official') params.set('is_formally_imported', 'true')
  if (itemType === 'material' && ['pending','archived'].includes(formalFilter.value)) { params.set('is_formally_imported', 'false'); params.set('unofficial_status', formalFilter.value) }
  if (itemType === 'machine' && modelFilter.value) params.set('machine_model', modelFilter.value)
  if (itemType === 'semi_finished' && semiKindFilter.value) params.set('semi_kind', semiKindFilter.value)
  return `/items?${params}`
}
async function revealItemRow(itemId: number) {
  await nextTick()
  await new Promise<void>(resolve => requestAnimationFrame(() => resolve()))
  const container = listTableScrollRef.value
  const row = container?.querySelector<HTMLElement>(`tr[data-item-id="${itemId}"]`)
  if (!container || !row) return
  container.scrollTop = Math.max(0, row.offsetTop - (container.clientHeight - row.offsetHeight) / 2)
  row.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'auto' })
}
async function load() {
  loading.value = true; error.value = ''
  const loadType = type.value; const loadFilter = listFilter.value; const includeDeleted = showDeleted.value
  const loadState = listStateKey()
  try {
    const [result, all, ruleRows, modelRows, keyCodeRows] = await Promise.all([
      api<ItemPage>(listRequestPath(loadType, includeDeleted, loadFilter)),
      api<ItemPage>(`/items?limit=${ITEM_PAGE_SIZE}`), api<Rule[]>('/code-rules'),
      api<string[]>('/machine-models'), api<string[]>('/key-component-codes'),
    ])
    if (listStateKey() !== loadState) return
    if (listStateKey() !== loadState) return
    items.value = result.items; loadedListItemIds = new Set(result.items.map(item => item.id)); injectedListItemId = 0
    itemTotal.value = result.total; listLoadedCount.value = result.items.length
    allItems.value = [...new Map([...all.items, ...allItems.value].map(item => [item.id, item])).values()]
      .sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
    allItemsTotal.value = all.total; candidateLoadedCount.value = all.items.length; rules.value = ruleRows
    machineModels.value = modelRows; keyComponentCodes.value = keyCodeRows
    const requestedId = Number(route.query.id || 0)
    if (requestedId) {
      let requested = items.value.find(row => row.id === requestedId) || allItems.value.find(row => row.id === requestedId)
      if (!requested) {
        const fetched = await api<Item>(`/items/${requestedId}`)
        if (type.value !== loadType || listFilter.value !== loadFilter || fetched.item_type !== loadType) return
        requested = fetched
        allItems.value = [...allItems.value, fetched].sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
      }
      if (requested && !matchesListFilter(requested, loadType, loadFilter)) requested = undefined
      const shouldReveal = route.query.locate === '1'
      if (requested && selected.value?.id !== requested.id) await choose(requested, shouldReveal)
      else if (requested && shouldReveal) { ensureItemInList(requested); revealSelectedItemId=requested.id; await revealItemRow(requested.id) }
    } else if (selected.value) {
      const currentSelected = selected.value
      let same = items.value.find(row => row.id === currentSelected.id) || allItems.value.find(row => row.id === currentSelected.id)
      if (same && !matchesListFilter(same, loadType, loadFilter)) same = undefined
      if (!same && currentSelected.item_type === loadType && matchesListFilter(currentSelected, loadType, loadFilter)) same = currentSelected
      if (same) {
        if (revealSelectedItemId === same.id) ensureItemInList(same)
        selected.value = same
        await refreshDetail()
        if (tab.value === 'basic') syncEditForm()
        if (revealSelectedItemId === same.id) await revealItemRow(same.id)
      } else selected.value = null
    }
  } catch (event) { error.value = (event as Error).message } finally { loading.value = false }
}
async function loadMoreListItems() {
  if (!hasMoreListItems.value || listLoadingMore.value) return
  listLoadingMore.value = true; error.value = ''
  const loadType = type.value; const includeDeleted = showDeleted.value; const loadFilter = listFilter.value
  const loadState = listStateKey()
  try {
    const result = await api<ItemPage>(listRequestPath(loadType, includeDeleted, loadFilter, listLoadedCount.value))
    if (listStateKey() !== loadState) return
    result.items.forEach(item => loadedListItemIds.add(item.id))
    items.value = [...new Map([...items.value, ...result.items].map(item => [item.id, item])).values()].sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
    itemTotal.value = result.total; listLoadedCount.value = loadedListItemIds.size
    if (injectedListItemId && loadedListItemIds.has(injectedListItemId)) injectedListItemId = 0
  } catch (event) { error.value = (event as Error).message } finally { listLoadingMore.value = false }
}
async function loadMoreCandidateItems() {
  if (!hasMoreCandidateItems.value || candidateLoadingMore.value) return
  candidateLoadingMore.value = true; error.value = ''
  try {
    const result = await api<ItemPage>(`/items?limit=${ITEM_PAGE_SIZE}&offset=${candidateLoadedCount.value}`)
    allItems.value = [...new Map([...allItems.value, ...result.items].map(item => [item.id, item])).values()]
      .sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
    candidateLoadedCount.value = Math.min(result.total, candidateLoadedCount.value + result.items.length)
    allItemsTotal.value = result.total
  } catch (event) { error.value = (event as Error).message } finally { candidateLoadingMore.value = false }
}
function searchCurrentTypeCandidates(query: string) { searchCandidateItems(query, { item_type: type.value }) }
function searchListCandidates(query: string) {
  const filters: Record<string, string> = { item_type: type.value }
  filters.include_disabled=String(showDeleted.value)
  if(type.value==='material'&&materialStatusFilter.value)filters.status=materialStatusFilter.value
  if(type.value==='material'&&componentFilter.value)filters.has_components=componentFilter.value
  if (listFilter.value) filters[type.value === 'material' ? 'source_type' : 'status'] = listFilter.value
  if (type.value === 'material' && formalFilter.value === 'official') filters.is_formally_imported = 'true'
  if (type.value === 'material' && ['pending','archived'].includes(formalFilter.value)) { filters.is_formally_imported = 'false'; filters.unofficial_status = formalFilter.value }
  if (type.value === 'machine' && modelFilter.value) filters.machine_model = modelFilter.value
  if (type.value === 'semi_finished' && semiKindFilter.value) filters.semi_kind = semiKindFilter.value
  searchCandidateItems(query, filters)
}
function searchAllTypeCandidates(query: string) { searchCandidateItems(query) }
function searchMaterialCandidates(query: string) { searchCandidateItems(query, { item_type: 'material' }) }
function reloadList() {
  loadedListItemIds = new Set(); injectedListItemId = 0; listLoadedCount.value = 0; itemTotal.value = 0
  load()
}
function applyListFilter() {
  cancelCandidateSearch(); searchItemId.value = 0; revealSelectedItemId = 0; batchSelected.value = []
  selected.value = null; detail.value = null; tree.value = []; production.value = []; references.value = []; history.value = []
  reloadList()
}
function applyKeywordSearch(query: string) {
  listQuery.value = query.trim()
  applyListFilter()
  message.value = listQuery.value ? `已按“${listQuery.value}”筛选下方全部匹配物料` : '已恢复当前类别全部物料'
}
async function choose(item: Item, revealInList = false) {
  revealSelectedItemId = revealInList ? item.id : 0
  if (revealInList) ensureItemInList(item)
  selected.value = item; tab.value = 'basic'; referenceFilter.value = 'all'; message.value = ''; error.value = ''
  syncBomSwitchDefaults(item)
  if (item.deleted_at) { detail.value = item; if (revealInList) await revealItemRow(item.id); return }
  await refreshDetail()
  if (selected.value?.id !== item.id) return
  syncEditForm()
  await loadTree()
  if (selected.value?.id !== item.id) return
  if(route.query.bom_path){tab.value='bom';focusedBomPath.value=String(route.query.bom_path);pathEditor.value=tree.value.find(row=>row.line_path.join('/')===String(route.query.bom_path))||null;const query={...route.query};delete query.bom_path;await router.replace({query})}
  if (revealInList) await revealItemRow(item.id)
}
function syncEditForm() {
  if (!detail.value) return
  Object.assign(edit, { name: detail.value.name, specification: detail.value.specification || '', unit: detail.value.unit, status: detail.value.status || '', source_type: detail.value.source_type || '', remark: detail.value.remark || '', previous_version_name: detail.value.previous_version_name || '', invoice_name: detail.value.invoice_name || '', material_attribute: detail.value.material_attribute || '', key_component_code: detail.value.key_component_code || '', machine_model: detail.value.machine_model || '', reason: '', similarity_confirmed: true })
}
function applyDetail(nextDetail: any) {
  detail.value = nextDetail
  if (selected.value) selected.value = { ...selected.value, ...nextDetail }
  Object.keys(lineQuantities).forEach(key => delete lineQuantities[Number(key)])
  for (const line of nextDetail.components || []) {
    lineQuantities[line.id] = String(line.quantity)
  }
}
async function refreshDetail() {
  if (!selected.value) return
  const itemId = selected.value.id
  const nextDetail = await api(`/items/${itemId}`)
  if (selected.value?.id === itemId) applyDetail(nextDetail)
}
function applyTree(nextTree: TreeRow[]) {
  tree.value = nextTree
  collapsedPaths.value = new Set()
}
async function refreshBomState() {
  if (!selected.value) return
  const itemId = selected.value.id
  const [nextDetail, nextTree] = await Promise.all([api(`/items/${itemId}`), api<TreeRow[]>(`/items/${itemId}/technical-bom?expand_materials=true`)])
  if (selected.value?.id !== itemId) return
  applyDetail(nextDetail); applyTree(nextTree)
}
async function restoreItem(){if(!selected.value)return;try{const restored=await api<Item>(`/items/${selected.value.id}/restore?reason=${encodeURIComponent('管理员恢复物料')}`,{method:'POST'});await load();await choose(restored);message.value='物料已恢复'}catch(event){error.value=(event as Error).message}}
async function batchExport(kind:string){if(!batchSelected.value.length)return;batchBusy.value=true;error.value='';try{await download(`/bom/batch-export/${kind}?${bomSwitchQuery(kind)}`,`批量${kind==='technical'?'技术':'生产'}BOM.zip`,{method:'POST',body:JSON.stringify(batchSelected.value)});message.value=`已生成 ${batchSelected.value.length} 个项目的批量${kind==='technical'?'技术':'生产'} BOM ZIP`}catch(event){error.value=(event as Error).message}finally{batchBusy.value=false}}
async function exportCurrentBom(kind: 'technical' | 'production') {
  if (!selected.value || !detail.value) return
  await download(`/items/${selected.value.id}/export/${kind}?${bomSwitchQuery(kind)}`, `${detail.value.code}-${detail.value.name}-${kind === 'technical' ? '技术' : '生产'}BOM.xlsx`)
}
async function selectAllVisible(){try{const result=await api<ItemPage>(listRequestPath(type.value,showDeleted.value,listFilter.value,0,10000));batchSelected.value=result.items.map(item=>item.id);message.value=`已选择当前筛选结果 ${result.items.length} 项`}catch(event){error.value=(event as Error).message}}
function invertVisibleSelection(){const selectedIds=new Set(batchSelected.value);items.value.filter(item=>!item.deleted_at).forEach(item=>selectedIds.has(item.id)?selectedIds.delete(item.id):selectedIds.add(item.id));batchSelected.value=[...selectedIds]}
function clearBatch(){batchSelected.value=[]}
function basicExportPath(selectedOnly:boolean){const params=new URLSearchParams({item_type:type.value,include_disabled:String(showDeleted.value)});if(type.value==='material'&&materialStatusFilter.value)params.set('status',materialStatusFilter.value);if(type.value==='material'&&componentFilter.value)params.set('has_components',componentFilter.value);if(listQuery.value.trim())params.set('q',listQuery.value.trim());if(listFilter.value)params.set(type.value==='material'?'source_type':'status',listFilter.value);if(type.value==='material'&&formalFilter.value==='official')params.set('is_formally_imported','true');if(type.value==='material'&&['pending','archived'].includes(formalFilter.value)){params.set('is_formally_imported','false');params.set('unofficial_status',formalFilter.value)}if(type.value==='machine'&&modelFilter.value)params.set('machine_model',modelFilter.value);if(type.value==='semi_finished'&&semiKindFilter.value)params.set('semi_kind',semiKindFilter.value);if(selectedOnly)batchSelected.value.forEach(id=>params.append('item_ids',String(id)));return `/items-basic-export?${params}`}
async function exportBasics(selectedOnly:boolean){if(selectedOnly&&!batchSelected.value.length)return;try{await download(basicExportPath(selectedOnly),`${labels[type.value]}基本信息-${selectedOnly?'已选':'筛选结果'}.xlsx`);message.value=`已导出${selectedOnly?'已选物料':'当前筛选结果'}基本信息`}catch(event){error.value=(event as Error).message}}
async function recommend() {
  if (!guide.ruleId) return
  const result = await api<{ recommended_code: string }>(`/code-rules/${guide.ruleId}/recommend`)
  form.code = result.recommended_code
  const rule = rules.value.find(row => row.id === guide.ruleId)
  form.material_attribute = rule?.material_attribute || ''
}
function ruleMatchesCode(code: string, rule: Rule) {
  const template = rule.pattern.match(/[0-9X.]+/i)?.[0] || rule.prefix
  const separator = template.lastIndexOf('.')
  if (separator < 0) return code.startsWith(rule.prefix)
  const bodyTemplate = template.slice(0, separator)
  const escapedBody = bodyTemplate.split('').map(character => character.toUpperCase() === 'X'
    ? '\\d'
    : character.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('')
  return new RegExp(`^${escapedBody}\\.\\d+$`).test(code)
}
async function applyItemCopy() {
  if (!copySourceId.value) return
  copyBusy.value = true; error.value = ''; message.value = ''
  try {
    const source = await api<any>(`/items/${copySourceId.value}`)
    if (source.item_type !== type.value) throw new Error(`只能复制同类型${labels[type.value] || '物料'}`)
    const sourceBaseCode = source.code
    const copyingUnofficial = type.value === 'material' && source.is_formally_imported === false
    const matchingRules = copyingUnofficial ? [] : rules.value.filter(rule => rule.active && rule.item_type === type.value && ruleMatchesCode(sourceBaseCode, rule))
    const sourceAttribute = String(source.material_attribute || '').trim()
    const matchingRule = [...matchingRules].sort((left, right) => {
      const leftAttribute = sourceAttribute && String(left.material_attribute || '').includes(sourceAttribute) ? 1 : 0
      const rightAttribute = sourceAttribute && String(right.material_attribute || '').includes(sourceAttribute) ? 1 : 0
      return rightAttribute - leftAttribute || right.prefix.length - left.prefix.length || left.id - right.id
    })[0]
    const ruleQuery = matchingRule ? `&code_rule_id=${matchingRule.id}` : ''
    const availability = copyingUnofficial
      ? { next_version_code: (await api<{estimated_code:string}>('/items/unofficial-code-preview')).estimated_code }
      : await api<CodeAvailability>(`/items/code-availability?code=${encodeURIComponent(sourceBaseCode)}&item_type=${type.value}&is_formally_imported=true${ruleQuery}`)
    Object.assign(guide, {
      large: matchingRule?.large_category || '',
      small: matchingRule?.small_category || '',
      ruleId: matchingRule?.id || 0,
    })
    Object.assign(form, {
      copy_source_id: source.id,
      code: availability.next_version_code || '', auxiliary_code: source.auxiliary_code || '',
      name: source.name, specification: source.specification || '', source_type: source.source_type || 'purchased',
      status: source.status || 'trial', unit: source.unit || 'pcs', remark: source.remark || '', previous_version_name: source.name,
      invoice_name: source.invoice_name || '', material_attribute: source.material_attribute || '',
      key_component_code: source.key_component_code || '', machine_model: source.machine_model || '',
      is_formally_imported: source.is_formally_imported !== false,
      reason: `复制${labels[type.value] || '物料'} ${source.code} 新建`, similarity_confirmed: true,
      components: (source.components || []).map((line: BomLine) => ({
        child_item_id: (line as any).base_child_item_id || line.child_item_id, quantity: line.quantity, sort_order: line.sort_order,
        line_remark: line.line_remark || '', alternative_group_id: line.alternative_group_id || null,
        child: line.child,
      })),
    })
    message.value = `已复制 ${source.code} 的档案${source.components?.length ? '和组成' : ''}${matchingRule ? '，并同步编码分类与规则' : '；源编码不符合当前标准规则，请重新选择分类与规则'}，请核对新编码后创建`
  } catch (event) { error.value = (event as Error).message } finally { copyBusy.value = false }
}
function useCodeSuggestion(code?: string) { if (code) form.code = code }
function queueCodeCheck(code: string) {
  if (codeCheckTimer) window.clearTimeout(codeCheckTimer)
  const request = ++codeCheckRequest
  codeCheck.value = null
  if (!showCreate.value || !code.trim()) { codeChecking.value = false; return }
  if (type.value === 'material' && !form.is_formally_imported) {
    codeCheck.value = { valid: true, code, exists: false, message: '预计编号；最终编号在提交事务时分配' }
    codeChecking.value = false
    return
  }
  codeChecking.value = true
  codeCheckTimer = window.setTimeout(async () => {
    try {
      const ruleQuery = guide.ruleId ? `&code_rule_id=${guide.ruleId}` : ''
      const result = await api<CodeAvailability>(`/items/code-availability?code=${encodeURIComponent(code.trim())}&item_type=${type.value}&is_formally_imported=${type.value!=='material'||form.is_formally_imported}${ruleQuery}`)
      if (request === codeCheckRequest && form.code.trim() === code.trim()) codeCheck.value = result
    } catch (event) {
      if (request === codeCheckRequest) codeCheck.value = { valid: false, code: code.trim(), exists: false, message: (event as Error).message }
    } finally { if (request === codeCheckRequest) codeChecking.value = false }
  }, 280)
}
function queueKeyComponentCheck(value: string, excludeId?: number) {
  if (keyCodeTimer) window.clearTimeout(keyCodeTimer)
  keyCodeCheck.value = null
  if (!String(value || '').trim()) return
  keyCodeTimer = window.setTimeout(async () => {
    try {
      const exclude = excludeId ? `&exclude_id=${excludeId}` : ''
      keyCodeCheck.value = await api<KeyCodeCheck>(`/items/key-component-code-availability?value=${encodeURIComponent(value)}${exclude}`)
    } catch (event) { keyCodeCheck.value = { valid: false, message: (event as Error).message } }
  }, 250)
}
function addComponent() {
  if (!componentDraft.child_item_id) return
  const child = allItems.value.find(row => row.id === componentDraft.child_item_id)
  if (!child) { error.value = '未找到所选组成物料，请重新搜索选择'; return }
  if (form.components.some((row: any) => row.child_item_id === componentDraft.child_item_id)) {
    error.value = `组成中已存在 ${child.code} ${child.name}，不能重复加入`
    return
  }
  error.value = ''
  form.components.push({ ...componentDraft, child })
  Object.assign(componentDraft, { child_item_id: 0, quantity: '1', sort_order: form.components.length + 2, line_remark: '' })
}
async function create() {
  error.value = ''; message.value = ''
  try {
    const payload = { ...form, code: type.value==='material'&&!form.is_formally_imported?null:form.code, code_rule_id: type.value==='material'&&!form.is_formally_imported?null:guide.ruleId || null, item_type: type.value, source_type: type.value === 'material' ? form.source_type : null, status: type.value === 'material' ? (form.status==='disabled'?'disabled':'active') : form.status, components: form.components.map(({ child, ...row }: any) => row) }
    const created = await api<Item>('/items', { method: 'POST', body: JSON.stringify(payload) })
    showCreate.value = false; resetForm(); await load(); await choose(created); message.value = `物料创建成功，最终编号：${created.code}`
  } catch (event) { error.value = (event as Error).message }
}
function openEditReason() {
  if (!selected.value) return
  edit.reason = ''
  showEditReason.value = true
}
async function saveEdit() {
  if (!selected.value || !edit.reason.trim()) return
  editSaving.value = true
  try {
    const itemId = selected.value.id
    const payload = { ...edit, status: edit.status, source_type: type.value === 'material' ? edit.source_type : undefined, key_component_code: type.value === 'material' ? edit.key_component_code : undefined, machine_model: type.value === 'machine' ? edit.machine_model : undefined }
    await api(`/items/${itemId}`, { method: 'PATCH', body: JSON.stringify(payload) })
    localStorage.setItem(ITEM_UPDATED_STORAGE_KEY, JSON.stringify({ itemId, updatedAt: Date.now() }))
    showEditReason.value = false
    await load(); message.value = '修改已保存'
  } catch (event) { error.value = (event as Error).message } finally { editSaving.value = false }
}
function openPromote(){if(!detail.value||detail.value.is_formally_imported!==false||detail.value.unofficial_status!=='pending')return;Object.assign(promoteGuide,{large:'',small:'',ruleId:0});Object.assign(promoteForm,{code:'',auxiliary_code:detail.value.auxiliary_code||'',name:detail.value.name,specification:detail.value.specification||'',source_type:detail.value.source_type||'purchased',unit:detail.value.unit||'pcs',remark:detail.value.remark||'',previous_version_name:detail.value.previous_version_name||'',invoice_name:detail.value.invoice_name||'',material_attribute:detail.value.material_attribute||'',key_component_code:detail.value.key_component_code||'',similarity_confirmed:false,reason:''});promoteCheck.value=null;keyCodeCheck.value=null;showPromote.value=true}
async function recommendPromote(){if(!promoteGuide.ruleId)return;const result=await api<{recommended_code:string}>(`/code-rules/${promoteGuide.ruleId}/recommend`);promoteForm.code=result.recommended_code;const rule=rules.value.find(row=>row.id===promoteGuide.ruleId);promoteForm.material_attribute=rule?.material_attribute||promoteForm.material_attribute;queuePromoteCheck()}
function queuePromoteCheck(){if(promoteCheckTimer)window.clearTimeout(promoteCheckTimer);promoteCheck.value=null;if(!showPromote.value||!promoteForm.code.trim()||!promoteGuide.ruleId)return;promoteChecking.value=true;promoteCheckTimer=window.setTimeout(async()=>{try{promoteCheck.value=await api<CodeAvailability>(`/items/code-availability?code=${encodeURIComponent(promoteForm.code.trim())}&item_type=material&is_formally_imported=true&code_rule_id=${promoteGuide.ruleId}`)}catch(event){promoteCheck.value={valid:false,code:promoteForm.code,exists:false,message:(event as Error).message}}finally{promoteChecking.value=false}},250)}
async function promoteMaterial(){if(!selected.value||!promoteGuide.ruleId||!promoteCheck.value?.valid||promoteCheck.value.exists||!promoteForm.reason.trim())return;promoteBusy.value=true;error.value='';try{const promoted=await api<Item>(`/items/${selected.value.id}/promote`,{method:'POST',body:JSON.stringify({...promoteForm,code_rule_id:promoteGuide.ruleId})});showPromote.value=false;await load();await choose(promoted,true);message.value=`已创建正式物料 ${promoted.code}；来源未正式物料已封存`}catch(event){error.value=(event as Error).message}finally{promoteBusy.value=false}}

async function refreshUnofficialEstimate(){if(type.value!=='material'||form.is_formally_imported)return;try{const result=await api<{estimated_code:string}>('/items/unofficial-code-preview');unofficialEstimate.value=result.estimated_code;form.code=result.estimated_code;codeCheck.value={valid:true,code:result.estimated_code,exists:false,message:'预计编号；最终编号在提交事务时分配'}}catch(event){error.value=(event as Error).message}}
function openCreate(){resetForm();showCreate.value=true}
async function deleteItem() {
  if (!selected.value || !confirm('确认彻底删除该物料？删除后无法恢复，正式编码将释放；被引用的物料不能删除。')) return
  try { await api(`/items/${selected.value.id}?reason=${encodeURIComponent('人工删除')}`, { method: 'DELETE' }); selected.value = null; detail.value = null; await load() } catch (event) { error.value = (event as Error).message }
}
async function addBom() {
  if (!selected.value || !bomDraft.child_item_id) return
  bomBusy.value = true; error.value = ''
  try { await api(`/items/${selected.value.id}/bom`, { method: 'POST', body: JSON.stringify(bomDraft) }); await refreshBomState(); Object.assign(bomDraft,{child_item_id:0,quantity:'1',line_remark:'',reason:'新增 BOM 组成'}); message.value = 'BOM 组成已添加，子物料表和层级树已刷新' } catch (event) { error.value = (event as Error).message } finally { bomBusy.value = false }
}
async function saveLineQuantity(line: BomLine) {
  const quantity = Number(lineQuantities[line.id])
  if (!Number.isFinite(quantity) || quantity <= 0) { error.value = 'BOM 数量必须大于 0'; return }
  if (String(lineQuantities[line.id]) === String(line.quantity)) { message.value = '数量没有变化'; return }
  savingLineId.value = line.id; error.value = ''
  try { await api(`/bom-lines/${line.id}`, { method: 'PATCH', body: JSON.stringify({ quantity: lineQuantities[line.id], reason: `修改 ${line.child.code} 的 BOM 数量` }) }); await refreshBomState(); message.value = `${line.child.code} 的数量已保存，子物料表和层级树已刷新` } catch (event) { error.value = (event as Error).message } finally { savingLineId.value = 0 }
}
async function deleteBom(line: BomLine) {
  if (!confirm(`移除 ${line.child.code}？`)) return
  try { await apiWithImpactConfirmation(`/bom-lines/${line.id}?reason=${encodeURIComponent('移除 BOM 组成')}`, { method: 'DELETE' }); await refreshBomState(); message.value='BOM 组成已移除，子物料表和层级树已刷新' } catch(event){error.value=(event as Error).message}
}
function openReplace(line: BomLine) {
  replaceLine.value = line
  Object.assign(replaceForm, { child_item_id: 0, reason: `将 ${line.child.code} 替换为其他物料` })
  error.value = ''; message.value = ''
}
async function confirmReplace() {
  if (!replaceLine.value || !replaceForm.child_item_id || !replaceForm.reason.trim()) return
  replaceBusy.value = true; error.value = ''
  try {
    const result = await apiWithImpactConfirmation<{message:string}>(`/bom-lines/${replaceLine.value.id}/replace`, { method: 'POST', body: JSON.stringify(replaceForm) })
    replaceLine.value = null
    await refreshBomState()
    message.value = result.message
  } catch (event) { error.value = (event as Error).message } finally { replaceBusy.value = false }
}
async function move(line: BomLine, direction: number) {
  const rows = [...detail.value.components] as BomLine[]; const index = rows.findIndex(row => row.id === line.id); const target = index + direction
  if (target < 0 || target >= rows.length || !selected.value) return
  ;[rows[index], rows[target]] = [rows[target], rows[index]]
  await api(`/items/${selected.value.id}/bom/reorder`, { method: 'POST', body: JSON.stringify({ line_ids: rows.map(row => row.id), reason: '界面调整顺序' }) })
  await refreshBomState(); message.value='BOM 显示顺序已更新'
}
async function loadTab(name: string) {
  tab.value = name; if (!selected.value) return
  if (name === 'basic' || name === 'bom') await loadTree()
  if (name === 'technical') await loadTechnicalTree()
  if (name === 'production') production.value = await api(`/items/${selected.value.id}/production-bom?${bomSwitchQuery('production')}`)
  if (name === 'references') references.value = await api(`/items/${selected.value.id}/references`)
  if (name === 'history') history.value = await api(`/items/${selected.value.id}/history`)
}
async function loadTree() {
  if (!selected.value) return
  applyTree(await api(`/items/${selected.value.id}/technical-bom?expand_materials=true`))
}
async function loadTechnicalTree() {
  if (!selected.value) return
  applyTree(await api(`/items/${selected.value.id}/technical-bom?${bomSwitchQuery('technical')}`))
}
function defaultMaterialExpansion(item: Item) { return item.item_type === 'material' }
function syncBomSwitchDefaults(item: Item) {
  const fallback = defaultMaterialExpansion(item)
  if (sessionStorage.getItem('bom_switch_technical_materials') === null) technicalExpandMaterials.value = fallback
  if (sessionStorage.getItem('bom_switch_production_materials') === null) productionExpandMaterials.value = fallback
}
function bomSwitchQuery(kind: string) {
  const alternatives = kind === 'technical' ? technicalShowAlternatives.value : productionShowAlternatives.value
  const materials = kind === 'technical' ? technicalExpandMaterials.value : productionExpandMaterials.value
  return new URLSearchParams({ show_alternatives: String(alternatives), expand_materials: String(materials) }).toString()
}
async function changeBomSwitch(kind: 'technical' | 'production', option: 'alternatives' | 'materials') {
  const value = kind === 'technical'
    ? (option === 'alternatives' ? technicalShowAlternatives.value : technicalExpandMaterials.value)
    : (option === 'alternatives' ? productionShowAlternatives.value : productionExpandMaterials.value)
  sessionStorage.setItem(`bom_switch_${kind}_${option}`, String(value))
  if (kind === 'technical' && tab.value === 'technical') await loadTechnicalTree()
  if (kind === 'production' && tab.value === 'production' && selected.value) production.value = await api(`/items/${selected.value.id}/production-bom?${bomSwitchQuery('production')}`)
}
function hasTreeChildren(row: TreeRow) {
  const index = tree.value.indexOf(row)
  return (tree.value[index + 1]?.level || 0) > row.level
}
function toggleTree(row: TreeRow) {
  const next = new Set(collapsedPaths.value); const key = row.path.join('-')
  next.has(key) ? next.delete(key) : next.add(key); collapsedPaths.value = next
}
function expandAll() { collapsedPaths.value = new Set() }
function collapseAll() {
  const next = new Set<string>()
  tree.value.forEach((row, index) => { if ((tree.value[index + 1]?.level || 0) > row.level) next.add(row.path.join('-')) })
  collapsedPaths.value = next
}
async function previewItem(item: Item) {
  const request = ++quickViewRequest
  quickViewItem.value = { ...item }
  quickViewLoading.value = true
  quickViewError.value = ''
  try {
    const fullItem = await api<any>(`/items/${item.id}`)
    if (request === quickViewRequest) quickViewItem.value = fullItem
  } catch (event) {
    if (request === quickViewRequest) quickViewError.value = (event as Error).message
  } finally {
    if (request === quickViewRequest) quickViewLoading.value = false
  }
}
function closeQuickView() {
  quickViewRequest += 1
  quickViewItem.value = null
  quickViewLoading.value = false
  quickViewError.value = ''
  externalDetailOpened = false
  externalDetailBlurred = false
}
function markExternalDetailOpened() {
  externalDetailOpened = true
  externalDetailBlurred = false
}
function handleWindowBlur() {
  if (externalDetailOpened) externalDetailBlurred = true
}
async function refreshQuickViewContext() {
  if (!quickViewItem.value || !selected.value) return
  const previewId = quickViewItem.value.id
  const parentId = selected.value.id
  try {
    const previewPromise = api<any>(`/items/${previewId}`)
    const detailPromise = api<any>(`/items/${parentId}`)
    const treePromise = ['basic', 'bom', 'technical'].includes(tab.value)
      ? api<TreeRow[]>(`/items/${parentId}/technical-bom?${tab.value==='technical'?bomSwitchQuery('technical'):'expand_materials=true'}`)
      : Promise.resolve<TreeRow[] | null>(null)
    const productionPromise = tab.value === 'production'
      ? api<any[]>(`/items/${parentId}/production-bom?${bomSwitchQuery('production')}`)
      : Promise.resolve<any[] | null>(null)
    const referencesPromise = tab.value === 'references'
      ? api<any[]>(`/items/${parentId}/references`)
      : Promise.resolve<any[] | null>(null)
    const historyPromise = tab.value === 'history'
      ? api<any[]>(`/items/${parentId}/history`)
      : Promise.resolve<any[] | null>(null)
    const [nextPreview, nextDetail, nextTree, nextProduction, nextReferences, nextHistory] = await Promise.all([
      previewPromise, detailPromise, treePromise, productionPromise, referencesPromise, historyPromise,
    ])
    if (quickViewItem.value?.id === previewId) quickViewItem.value = nextPreview
    if (selected.value?.id !== parentId) return
    applyDetail(nextDetail)
    if (nextTree) {
      const previousCollapsed = new Set(collapsedPaths.value)
      tree.value = nextTree
      const validPaths = new Set(nextTree.map(row => row.path.join('-')))
      collapsedPaths.value = new Set([...previousCollapsed].filter(path => validPaths.has(path)))
    }
    if (nextProduction) production.value = nextProduction
    if (nextReferences) references.value = nextReferences
    if (nextHistory) history.value = nextHistory
  } catch (event) {
    quickViewError.value = `返回原页面时刷新失败：${(event as Error).message}`
  }
}
async function refreshAfterExternalEdit() {
  if (!externalDetailOpened || !externalDetailBlurred) return
  externalDetailOpened = false
  externalDetailBlurred = false
  await refreshQuickViewContext()
}
function handleItemUpdated(event: StorageEvent) {
  if (event.key !== ITEM_UPDATED_STORAGE_KEY || !event.newValue || !quickViewItem.value) return
  try {
    const update = JSON.parse(event.newValue) as { itemId?: number }
    if (Number(update.itemId) !== Number(quickViewItem.value.id)) return
    externalDetailOpened = false
    externalDetailBlurred = false
    void refreshQuickViewContext()
  } catch { /* Ignore unrelated or malformed browser storage values. */ }
}
function back() {
  if (route.query.parent_type && route.query.parent_id) {
    router.push({ path: `/items/${route.query.parent_type}`, query: { id: String(route.query.parent_id), locate: '1' } })
  } else router.back()
}
function showChangeValue(value: unknown) {
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (typeof value === 'string') return displayLabel(value)
  return value == null || value === '' ? '—' : String(value)
}
function historyAction(event: any) {
  if (event.entity_type === 'bom_line' && event.action === 'delete') return '移除组成'
  return actionLabels[event.action] || event.action
}
async function copyVersion() {
  if (!selected.value) return
  try { const copied = await api<Item>(`/items/${selected.value.id}/copy`, { method: 'POST', body: JSON.stringify({ mode: 'new_version', reason: '从界面复制新版本' }) }); await load(); await choose(copied); message.value = `已创建版本 ${copied.code}` } catch (event) { error.value = (event as Error).message }
}
watch([searchItemId, listSearchCandidates], async ([id, candidates]) => {
  if (!id) return
  const item = candidates.find(row => row.id === id)
  if (item && selected.value?.id !== item.id) await choose(item, true)
})
watch([type, () => route.query.id], ([nextType], [previousType]) => { if(nextType!==previousType){listFilter.value='';formalFilter.value='';modelFilter.value='';semiKindFilter.value='';listQuery.value=''} cancelCandidateSearch(); searchItemId.value = 0; revealSelectedItemId=0; batchSelected.value=[]; selected.value = null; detail.value = null; resetForm(); reloadList() })
watch([() => form.code, () => guide.ruleId, () => form.is_formally_imported, showCreate, type], ([code]) => queueCodeCheck(String(code || '')))
watch(() => promoteForm.code, () => queuePromoteCheck())
watch(() => promoteGuide.ruleId, () => queuePromoteCheck())
watch(() => form.is_formally_imported, async formal => {
  if (!showCreate.value || type.value !== 'material') return
  if (!formal) { Object.assign(guide,{large:'',small:'',ruleId:0}); await refreshUnofficialEstimate() }
  else { unofficialEstimate.value=''; form.code=''; codeCheck.value=null }
})
onMounted(() => {
  load()
  window.addEventListener('blur', handleWindowBlur)
  window.addEventListener('focus', refreshAfterExternalEdit)
  window.addEventListener('storage', handleItemUpdated)
  requestAnimationFrame(() => {
    listPaneWidth.value = storedListPaneWidth
      ? clampListPaneWidth(storedListPaneWidth)
      : clampListPaneWidth((splitRef.value?.getBoundingClientRect().width || 1080) * .52)
  })
})
onBeforeUnmount(() => { document.body.classList.remove('split-resizing'); if (codeCheckTimer) window.clearTimeout(codeCheckTimer); if(keyCodeTimer)window.clearTimeout(keyCodeTimer); if(promoteCheckTimer)window.clearTimeout(promoteCheckTimer); window.removeEventListener('blur', handleWindowBlur); window.removeEventListener('focus', refreshAfterExternalEdit); window.removeEventListener('storage', handleItemUpdated) })
</script>

<template>
  <header class="page-head"><div><h1>{{ labels[type] }}管理</h1><p class="subtitle">查询、创建和维护{{ labels[type] }}及其 BOM 关系</p></div><button v-if="canWrite" class="btn" data-testid="new-item" @click="openCreate">新建{{ labels[type] }}</button></header>
  <div v-if="error" class="notice error" role="alert">{{ error }}</div><div v-if="message" class="notice">{{ message }}</div>
  <div ref="splitRef" class="split resizable-split" :class="{'is-resizing':resizingPanes}" :style="{'--list-pane-width':`${listPaneWidth}px`}">
    <section class="card">
      <div class="toolbar"><ItemAutocomplete v-model="searchItemId" :items="listSearchCandidates" :has-more="hasMoreListItems" :loading-more="listLoadingMore||loading" :loaded-items="listSearchCandidates.length" :total-items="itemTotal" :searching="candidateSearching" :search-total="candidateSearchTotal" :enter-select="false" label="搜索物料" placeholder="输入后按回车筛选下方全部结果；也可选择候选快速定位" @search="searchListCandidates" @submit="applyKeywordSearch" @load-more="loadMoreListItems"/><button v-if="listQuery" type="button" class="btn secondary small" @click="applyKeywordSearch('')">清除关键词“{{listQuery}}”</button><label v-if="type==='material'">来源筛选 <select v-model="listFilter" aria-label="原材料来源筛选" @change="applyListFilter"><option value="">全部来源</option><option value="purchased">外购</option><option value="outsourced">外协</option><option value="self_made">自制</option></select></label><label v-else>状态筛选 <select v-model="listFilter" aria-label="物料状态筛选" @change="applyListFilter"><option value="">全部状态</option><option v-if="type!=='material'" value="trial">试制</option><option value="active">在用</option><option value="disabled">停用</option></select></label><label v-if="type==='material'">导入状态 <select v-model="formalFilter" aria-label="正式导入状态筛选" @change="applyListFilter"><option value="">全部</option><option value="official">正式导入</option><option value="pending">待转正式</option><option value="archived">已转正式（封存）</option></select></label><label v-if="type==='machine'">机型 <select v-model="modelFilter" aria-label="整机机型筛选" @change="applyListFilter"><option value="">全部机型</option><option v-for="model in machineModels" :key="model" :value="model">{{model}}</option></select></label><label v-if="type==='semi_finished'">半成品分类 <select v-model="semiKindFilter" aria-label="半成品分类筛选" @change="applyListFilter"><option value="">全部分类</option><option value="normal">普通半成品</option><option value="combination">组合半成品</option></select></label><label><span><input v-model="showDeleted" type="checkbox" style="min-width:auto" @change="applyListFilter"/> 显示已停用</span></label><label v-if="type==='material'">状态<select v-model="materialStatusFilter" @change="applyListFilter"><option value="">全部状态</option><option value="active">在用</option><option value="disabled">停用</option></select></label><label v-if="type==='material'">下级组成<select v-model="componentFilter" @change="applyListFilter"><option value="">全部组成</option><option value="true">有下级组成</option><option value="false">无下级组成</option></select></label><span class="subtitle">当前筛选已加载 {{ listLoadedCount }} / {{ itemTotal }} 条</span></div>
      <div class="notice" style="margin-bottom:14px"><div class="toolbar" style="margin:0"><strong>批量选择与导出</strong><button class="btn secondary small" title="选择当前全部筛选结果（包括未加载分页）" @click="selectAllVisible">全选筛选结果</button><button class="btn secondary small" title="只反选当前已加载页面" @click="invertVisibleSelection">反选当前页</button><button class="btn secondary small" :disabled="!batchSelected.length" @click="clearBatch">清空</button><span>已选 {{ batchSelected.length }} 项</span><button class="btn secondary small" @click="exportBasics(false)">导出筛选结果基本信息</button><button class="btn secondary small" :disabled="!batchSelected.length" @click="exportBasics(true)">导出已选基本信息</button><button class="btn secondary small" :disabled="!batchSelected.length||batchBusy" @click="batchExport('technical')">批量导出技术 BOM ZIP</button><button class="btn secondary small" :disabled="!batchSelected.length||batchBusy" @click="batchExport('production')">批量导出生产 BOM ZIP</button></div></div>
      <div ref="listTableScrollRef" class="table-wrap" data-testid="item-list-scroll"><table data-testid="item-list-table"><thead><tr><th>选择</th><th>系统物料编码</th><th>名称</th><th>规格型号</th><th>状态/来源</th></tr></thead><tbody>
        <tr v-for="item in items" :key="item.id" class="clickable" :class="{'selected-row': selected?.id===item.id}" :data-item-id="item.id" :data-item-code="item.code" :aria-selected="selected?.id===item.id" @click="choose(item)"><td><input v-model="batchSelected" type="checkbox" :value="item.id" :disabled="!!item.deleted_at" style="min-width:auto" @click.stop/></td><td><strong :class="{warn:item.is_formally_imported===false}">{{ item.code }}</strong> <span v-if="item.unofficial_status==='pending'" class="tag warn">待转正式</span><span v-else-if="item.unofficial_status==='archived'" class="tag">已转正式（封存）</span></td><td>{{ item.name }} <span v-if="item.is_combination" class="tag">组合半成品</span></td><td>{{ item.specification || '—' }}</td><td><span class="tag" :class="{warn:item.status==='trial'||item.unofficial_status==='pending',red:item.status==='disabled'||item.deleted_at}">{{ item.deleted_at?'已删除':displayLabel(item.source_type || item.status) }}</span><span v-if="type==='material'&&item.status==='disabled'" class="tag red">停用</span></td></tr>
      </tbody></table><div v-if="!loading&&!items.length" class="empty">没有匹配的物料</div><div v-if="itemTotal" class="list-load-more" data-testid="item-list-load-more"><span>已加载 {{listLoadedCount}} / {{itemTotal}} 条</span><button v-if="hasMoreListItems" type="button" class="btn secondary small" :disabled="listLoadingMore" @click="loadMoreListItems">{{listLoadingMore?'正在加载…':'继续加载下一批'}}</button><strong v-else>已显示全部</strong></div></div>
    </section>
    <div class="split-resizer" role="separator" aria-label="调整物料列表和详情栏宽度" aria-orientation="vertical" :aria-valuenow="listPaneWidth" aria-valuemin="360" tabindex="0" title="左右拖动调整栏宽；双击恢复默认宽度" @pointerdown="startPaneResize" @pointermove="movePaneResize" @pointerup="stopPaneResize" @pointercancel="stopPaneResize" @keydown="resizePanesByKeyboard" @dblclick="resetPaneWidth"><span aria-hidden="true">⋮</span></div>
    <section v-if="detail" class="card" data-testid="item-detail">
      <div class="page-head"><div><button v-if="route.query.from" class="link-button" @click="back">← 返回 {{ route.query.from }}</button><h2>{{ detail.code }} <span v-if="detail.is_combination" class="tag">组合半成品</span><span v-if="detail.unofficial_status==='archived'" class="tag">已转正式（封存）</span></h2><p class="subtitle">{{ detail.name }}</p></div><div class="toolbar"><button v-if="detail.deleted_at&&canDelete&&detail.unofficial_status!=='archived'" class="btn small" @click="restoreItem">恢复物料</button><button v-if="!detail.deleted_at&&type!=='material'&&canWrite" class="btn secondary small" @click="copyVersion">复制新版本</button><button v-if="!detail.deleted_at&&canDelete&&detail.unofficial_status!=='archived'" class="btn danger small" @click="deleteItem">删除</button></div></div>
      <div v-if="detail.deleted_at" class="notice error">该物料已软删除，仅可由管理员恢复。</div>
      <div v-if="detail.unofficial_status==='archived'" class="notice">封存来源，仅供历史参考。档案和 BOM 可以查看、导出，但不能修改、删除、恢复或再次转正式。</div>
      <div v-if="detail.promotion_trace?.deleted_promoted_to" class="notice">转成的正式物料已删除：{{detail.promotion_trace.deleted_promoted_to.code}}｜{{detail.promotion_trace.deleted_promoted_to.name}}</div>
      <div v-if="detail.unofficial_status==='archived'&&detail.promotion_trace?.promoted_to" class="notice">已转为正式物料：<button type="button" class="code-link" @click="previewItem(detail.promotion_trace.promoted_to)">{{detail.promotion_trace.promoted_to.code}}</button>｜{{detail.promotion_trace.promoted_to.name}}</div>
      <template v-if="true">
      <div class="tabs"><button :class="{active:tab==='basic'}" @click="loadTab('basic')">基本信息</button><button :class="{active:tab==='bom'}" @click="loadTab('bom')">BOM 编辑</button><button :class="{active:tab==='technical'}" @click="loadTab('technical')">技术 BOM</button><button :class="{active:tab==='production'}" @click="loadTab('production')">生产 BOM</button><button :class="{active:tab==='references'}" @click="loadTab('references')">反向追溯</button><button :class="{active:tab==='history'}" @click="loadTab('history')">变更记录</button></div>
      <form v-if="tab==='basic'" class="form-grid" :inert="detail.unofficial_status==='archived'" @submit.prevent="openEditReason">
        <label>名称<input v-model="edit.name" required /></label><label>规格型号<input v-model="edit.specification" /></label><label>单位<input v-model="edit.unit" /></label>
        <label v-if="type==='material'">来源<select v-model="edit.source_type"><option value="purchased">外购</option><option value="outsourced">外协</option><option value="self_made">自制</option></select></label><label>状态<select v-model="edit.status"><option v-if="type!=='material'" value="trial">试制</option><option value="active">在用</option><option value="disabled">停用</option></select></label>
        <label v-if="type==='material'">正式导入状态<input :value="detail.is_formally_imported?'正式导入':detail.unofficial_status==='archived'?'已转正式（封存）':'待转正式'" disabled /></label><label v-if="type==='material'">历史物料号<input :value="detail.historical_item_code||''" disabled /></label><label v-if="type==='material'">关键器件码<input v-model="edit.key_component_code" list="key-component-code-options" maxlength="5" pattern="[A-Za-z0-9]{3}\.[A-Za-z0-9]" placeholder="例如 F33.A，可留空" @input="queueKeyComponentCheck(edit.key_component_code,detail.id)"/><small v-if="keyCodeCheck">{{keyCodeCheck.message}}<span v-for="item in keyCodeCheck.duplicate_items||[]" :key="item.id"><br/>{{item.code}}｜{{item.name}}</span></small></label>
        <label v-if="type==='machine'">机型<input v-model="edit.machine_model" list="machine-model-options" placeholder="可选择 R60、Y60、T65 等或手工输入" /></label>
        <label v-if="type==='material'">上一版本名称<input v-model="edit.previous_version_name" /></label><label v-if="type==='material'">发票名称<input v-model="edit.invoice_name" /></label><label v-if="type==='material'">材料属性<input v-model="edit.material_attribute" /></label>
        <div v-if="type!=='machine'" class="span-2"><strong>当前引用机型：</strong><template v-if="detail.ownership?.current_models?.length"><span v-for="group in detail.ownership.current_models" :key="group.model" class="tag" style="margin-left:6px" :title="group.machines.map((item:any)=>`${item.code} ${item.name}`).join('\n')">{{group.model}}（{{group.machines.length}}台）</span></template><span v-else>暂无</span><details v-if="detail.ownership?.history_models?.length" style="margin-top:8px"><summary>历史机型引用</summary><span v-for="group in detail.ownership.history_models" :key="group.model" class="tag" style="margin:6px 6px 0 0">{{group.model}}（{{group.machines.length}}台）</span></details></div>
        <label class="span-2">备注<textarea v-model="edit.remark" rows="2"/></label>
        <div v-if="type==='material'&&detail.unofficial_status!=='archived'&&detail.promotion_trace?.promoted_to" class="notice span-2">已转为正式物料：<button type="button" class="code-link" @click="previewItem(detail.promotion_trace.promoted_to)">{{detail.promotion_trace.promoted_to.code}}</button>｜{{detail.promotion_trace.promoted_to.name}}</div>
        <div v-if="type==='material'&&detail.promotion_trace?.promoted_from?.length" class="notice span-2">来源未正式物料：<template v-for="source in detail.promotion_trace.promoted_from" :key="source.id"><button type="button" class="code-link" @click="previewItem(source)">{{source.code}}</button>｜{{source.name}} </template></div>
        <div class="actions span-2"><button v-if="canModifyDetail" class="btn">保存修改</button><button v-if="canModifyDetail&&type==='material'&&detail.unofficial_status==='pending'" type="button" class="btn secondary" @click="openPromote">转为正式导入</button></div>
      </form>
      <div v-if="tab==='basic'" class="basic-bom-tree">
        <div class="toolbar" style="margin-top:18px"><h3 style="margin:0">完整层级结构</h3><button class="btn secondary small" @click="expandAll">全部展开</button><button class="btn secondary small" @click="collapseAll">全部收起</button><span class="subtitle">基本信息页可直接查看下级组成；点击编码快速查看物料</span></div>
        <div class="table-wrap"><table><thead><tr><th>层级/编码</th><th>类型</th><th>名称</th><th>规格型号</th><th>数量</th></tr></thead><tbody><tr v-for="row in visibleTree" :key="`basic-${row.path.join('-')}`"><td><div :style="{paddingLeft:`${Math.max(0,row.level-1)*20}px`}" class="tree-cell"><button v-if="hasTreeChildren(row)" class="tree-toggle" :aria-label="collapsedPaths.has(row.path.join('-'))?'展开':'收起'" @click="toggleTree(row)">{{ collapsedPaths.has(row.path.join('-')) ? '+' : '−' }}</button><span v-else class="tree-toggle-placeholder"></span><button class="code-link" :aria-label="`快速查看 ${row.item.code}`" @click="previewItem(row.item)">{{row.item.code}}</button></div></td><td>{{labels[row.item.item_type]}}</td><td>{{row.item.name}}</td><td>{{row.item.specification||'—'}}</td><td>{{row.quantity}}</td></tr></tbody></table><div v-if="!tree.length" class="empty">当前物料没有下级组成</div></div>
      </div>
      <div v-if="tab==='bom'">
        <div v-if="canModifyDetail" class="toolbar"><ItemAutocomplete v-model="bomDraft.child_item_id" :items="allowedChildren" :has-more="hasMoreCandidateItems" :loading-more="candidateLoadingMore" :loaded-items="candidateLoadedCount" :total-items="allItemsTotal" :searching="candidateSearching" :search-total="candidateSearchTotal" label="搜索子物料" placeholder="输入编码、名称或规格，自动搜索全部物料" @search="searchAllTypeCandidates" @load-more="loadMoreCandidateItems"/><input v-model="bomDraft.quantity" type="number" min="0.000001" step="any" style="width:100px" aria-label="BOM数量"/><button class="btn small" :disabled="bomBusy||!bomDraft.child_item_id" @click="addBom">{{ bomBusy?'正在添加…':'添加组成' }}</button></div>
        <div class="table-wrap"><table data-testid="direct-bom-table"><thead><tr><th>顺序</th><th>子物料</th><th>名称</th><th>数量</th><th>选配</th><th>操作</th></tr></thead><tbody><tr v-for="(line,index) in detail.components" :key="line.id"><td>{{ index+1 }}</td><td><button class="code-link" :aria-label="`快速查看 ${line.child.code}`" @click="previewItem(line.child)">{{ line.child.code }}</button></td><td>{{ line.child.name }}</td><td><div class="toolbar" style="margin:0;flex-wrap:nowrap"><input v-model="lineQuantities[line.id]" type="number" min="0.000001" step="any" style="width:90px" :aria-label="`${line.child.code} 数量`" :disabled="!canModifyDetail||savingLineId===line.id" @keyup.enter="saveLineQuantity(line)"/><button v-if="canModifyDetail" class="btn secondary small" :disabled="savingLineId===line.id||String(lineQuantities[line.id])===String(line.quantity)" @click="saveLineQuantity(line)">{{savingLineId===line.id?'保存中…':'保存数量'}}</button></div></td><td>在下方层级树查看及配置选配</td><td><template v-if="canModifyDetail"><button class="btn secondary small" @click="move(line,-1)">↑</button> <button class="btn secondary small" @click="move(line,1)">↓</button> <button class="btn secondary small" @click="openReplace(line)">替换</button> <button class="btn danger small" @click="deleteBom(line)">移除</button></template></td></tr></tbody></table><div v-if="!detail.components.length" class="empty">暂无直接子物料，请从上方搜索并添加组成</div></div>
        <div class="toolbar" style="margin-top:18px"><h3 style="margin:0">完整层级结构</h3><button class="btn secondary small" @click="expandAll">全部展开</button><button class="btn secondary small" @click="collapseAll">全部收起</button><span class="subtitle">点击“+”逐层查看单元、半成品和原材料</span></div>
        <table><thead><tr><th>层级/编码</th><th>类型</th><th>名称</th><th>数量</th><th>路径选配</th></tr></thead><tbody><tr v-for="row in visibleTree" :key="`bom-${row.sequence}-${row.path.join('-')}`" :class="{'selected-row':focusedBomPath===row.line_path.join('/')}"><td><div :style="{paddingLeft:`${Math.max(0,row.level-1)*20}px`}" class="tree-cell"><button v-if="hasTreeChildren(row)" class="tree-toggle" :aria-label="collapsedPaths.has(row.path.join('-'))?'展开':'收起'" @click="toggleTree(row)">{{ collapsedPaths.has(row.path.join('-')) ? '+' : '−' }}</button><span v-else class="tree-toggle-placeholder"></span><button class="code-link" :aria-label="`快速查看 ${row.item.code}`" @click="previewItem(row.item)">{{ row.item.code }}</button></div></td><td>{{ labels[row.item.item_type] }}</td><td>{{ row.item.name }}</td><td>{{ row.quantity }}</td><td><span v-if="row.is_backup_path" class="tag">备用选配</span><span v-else class="tag">{{row.configuration_owner ? (row.local_configuration ? (row.configuration_mode==='disabled'?'本路径禁用':'本路径自定义') : '继承自 '+row.configuration_owner.code) : '未配置'}}</span> <button v-if="type!=='material'&&(row.level===1||tree.find(r=>r.path.join('/')===row.path.slice(0,-1).join('/'))?.item.item_type!=='material')" class="btn secondary small" @click="focusedBomPath=row.line_path.join('/');pathEditor=row">{{canModifyDetail&&!row.is_backup_path?'配置选配':'查看选配'}}</button></td></tr></tbody></table>
      </div>
      <div v-if="tab==='technical'">
        <div class="toolbar">
          <button class="btn secondary small" @click="exportCurrentBom('technical')">导出技术 BOM Excel</button>
          <label><span><input v-model="technicalShowAlternatives" type="checkbox" style="min-width:auto" @change="changeBomSwitch('technical','alternatives')"/> 显示选配替代</span></label>
          <label><span><input v-model="technicalExpandMaterials" type="checkbox" style="min-width:auto" @change="changeBomSwitch('technical','materials')"/> 展开有下级组成的原材料</span></label>
          <button class="btn secondary small" @click="technicalDetailed=!technicalDetailed">{{technicalDetailed?'收起详细信息':'查看详细信息'}}</button>
          <template v-if="!technicalDetailed"><button class="btn secondary small" @click="expandAll">全部展开</button><button class="btn secondary small" @click="collapseAll">全部收起</button></template>
          <span class="subtitle">{{technicalDetailed?'以下 15 列与导出 Excel 顺序一致':'备用选配仅作展示，数量不计入当前生产用量'}}</span>
        </div>
        <div class="table-wrap">
          <table v-if="technicalDetailed" data-testid="technical-detail-table"><thead><tr><th>序号</th><th>层级</th><th>物料编码</th><th>名称</th><th>规格型号</th><th>单位</th><th>数量</th><th>备注</th><th>上一版本名称</th><th>发票名称</th><th>材料属性</th><th>选配状态</th><th>替代组</th><th>市场占比</th><th>变更记录</th></tr></thead><tbody><tr v-for="row in tree" :key="`tech-detail-${row.sequence}-${row.path.join('-')}`"><td>{{row.sequence}}</td><td class="tree-level-label">{{technicalLevelLabels.get(row.path.join('-'))}}</td><td><button class="code-link" :aria-label="`快速查看 ${row.item.code}`" @click="previewItem(row.item)">{{row.item.code}}</button></td><td>{{row.item.name}}</td><td>{{row.item.specification||'—'}}</td><td>{{row.item.unit}}</td><td>{{row.quantity}}</td><td>{{row.line_remark||row.item.remark||'—'}}</td><td>{{row.item.previous_version_name||'—'}}</td><td>{{row.item.invoice_name||'—'}}</td><td>{{row.item.material_attribute||'—'}}</td><td><span v-if="row.is_backup_path" class="tag warn">备用选配</span><span v-else-if="row.alternative_group_name" class="tag">当前选用</span><span v-else>—</span></td><td>{{row.alternative_group_name||'—'}}</td><td>{{row.market_share!==undefined&&row.market_share!==null?`${row.market_share}%`:'—'}}</td><td>{{row.latest_change_reason||'—'}}</td></tr></tbody></table>
          <table v-else><thead><tr><th>层级/编码</th><th>类型</th><th>名称</th><th>数量</th><th>选配状态</th><th>替代组</th><th>占比</th></tr></thead><tbody><tr v-for="row in visibleTree" :key="`tech-${row.sequence}-${row.path.join('-')}`"><td><div :style="{paddingLeft:`${Math.max(0,row.level-1)*20}px`}" class="tree-cell"><button v-if="hasTreeChildren(row)" class="tree-toggle" @click="toggleTree(row)">{{ collapsedPaths.has(row.path.join('-')) ? '+' : '−' }}</button><span v-else class="tree-toggle-placeholder"></span><button class="code-link" :aria-label="`快速查看 ${row.item.code}`" @click="previewItem(row.item)">{{ row.item.code }}</button></div></td><td>{{ labels[row.item.item_type] }}</td><td>{{ row.item.name }}</td><td>{{ row.quantity }}</td><td><span v-if="row.is_backup_path" class="tag warn">备用选配</span><span v-else-if="row.alternative_group_name" class="tag">当前选用</span><span v-else>—</span></td><td>{{row.alternative_group_name||'—'}}</td><td>{{row.market_share!==undefined&&row.market_share!==null?`${row.market_share}%`:'—'}}</td></tr></tbody></table>
        </div>
      </div>
      <div v-if="tab==='production'">
        <div class="toolbar">
          <button class="btn secondary small" @click="exportCurrentBom('production')">导出生产 BOM Excel</button>
          <label><span><input v-model="productionShowAlternatives" type="checkbox" style="min-width:auto" @change="changeBomSwitch('production','alternatives')"/> 显示选配替代</span></label>
          <label><span><input v-model="productionExpandMaterials" type="checkbox" style="min-width:auto" @change="changeBomSwitch('production','materials')"/> 展开有下级组成的原材料</span></label>
          <button class="btn secondary small" @click="productionDetailed=!productionDetailed">{{productionDetailed?'收起详细信息':'查看详细信息'}}</button>
          <span class="subtitle">{{productionDetailed?'以下 14 列与导出 Excel 顺序一致':'当前用量保持汇总；备用选配单独列出且不参与汇总'}}</span>
        </div>
        <div class="table-wrap">
          <table v-if="productionDetailed" data-testid="production-detail-table"><thead><tr><th>序号</th><th>物料编码</th><th>名称</th><th>规格型号</th><th>单位</th><th>数量</th><th>备注</th><th>上一版本名称</th><th>发票名称</th><th>材料属性</th><th>选配状态</th><th>替代组</th><th>市场占比</th><th>变更记录</th></tr></thead><tbody><tr v-for="row in production" :key="`prod-detail-${row.sequence}-${row.item.id}`"><td>{{row.sequence}}</td><td><button class="code-link" :aria-label="`快速查看 ${row.item.code}`" @click="previewItem(row.item)">{{row.item.code}}</button></td><td>{{row.item.name}}</td><td>{{row.item.specification||'—'}}</td><td>{{row.item.unit}}</td><td>{{row.quantity}}</td><td>{{row.item.remark||'—'}}</td><td>{{row.item.previous_version_name||'—'}}</td><td>{{row.item.invoice_name||'—'}}</td><td>{{row.item.material_attribute||'—'}}</td><td><span v-if="row.is_backup_path" class="tag warn">备用选配</span><span v-else>当前生产</span></td><td>{{row.alternative_group_name||'—'}}</td><td>{{row.market_share!==undefined&&row.market_share!==null?`${row.market_share}%`:'—'}}</td><td>{{row.latest_change_reason||'—'}}</td></tr></tbody></table>
          <table v-else><thead><tr><th>编码</th><th>原材料</th><th>数量</th><th>选配状态</th><th>替代组</th><th>占比</th></tr></thead><tbody><tr v-for="row in production" :key="`prod-${row.sequence}-${row.item.id}`"><td><button class="code-link" :aria-label="`快速查看 ${row.item.code}`" @click="previewItem(row.item)">{{ row.item.code }}</button></td><td>{{ row.item.name }}</td><td>{{ row.quantity }}</td><td><span v-if="row.is_backup_path" class="tag warn">备用选配（不计入汇总）</span><span v-else>当前生产</span></td><td>{{row.alternative_group_name||'—'}}</td><td>{{row.market_share!==undefined&&row.market_share!==null?`${row.market_share}%`:'—'}}</td></tr></tbody></table>
        </div>
      </div>
      <div v-if="tab==='references'"><p class="subtitle">路径按“上级父项 → … → 当前物料”显示；直接引用表示该父项的 BOM 中直接包含当前物料。</p><div class="toolbar"><label>引用关系筛选 <select v-model="referenceFilter" aria-label="引用关系筛选"><option value="all">全部引用</option><option value="direct">直接引用</option><option value="indirect">间接引用</option></select></label><span class="subtitle">显示 {{filteredReferences.length}} / {{references.length}} 条</span></div><table data-testid="references-table"><thead><tr><th>父项</th><th>关系</th><th>类型</th><th>可读路径</th></tr></thead><tbody><tr v-for="(row,index) in filteredReferences" :key="index"><td><button class="code-link" :aria-label="`快速查看 ${row.parent.code}`" @click="previewItem(row.parent)">{{ row.parent.code }}</button> {{ row.parent.name }}</td><td><span class="tag">{{ row.is_direct ? '直接引用' : '间接引用' }}</span></td><td>{{ labels[row.parent.item_type] }}</td><td><span v-for="(pathItem,pathIndex) in row.path_items" :key="pathItem.id"><button class="code-link" :aria-label="`快速查看 ${pathItem.code}`" @click="previewItem(pathItem)">{{ pathItem.code }}</button> {{ pathItem.name }}<span v-if="pathIndex<row.path_items.length-1"> → </span></span></td></tr></tbody></table><div v-if="!references.length" class="empty">当前未被其他 BOM 引用</div><div v-else-if="!filteredReferences.length" class="empty">当前筛选条件下没有引用记录</div></div>
      <div v-if="tab==='history'"><p class="subtitle">汇总本物料及各历史时点全部下级组成的档案、数量、新增和移除记录；组件后来被移除，也不会丢失其在装配期间发生的变更。</p><div class="table-wrap"><table data-testid="item-history-table"><thead><tr><th>时间</th><th>范围</th><th>变更对象</th><th>所在路径</th><th>操作</th><th>修改内容</th><th>原因</th></tr></thead><tbody><tr v-for="event in history" :key="event.id"><td>{{ new Date(event.created_at).toLocaleString('zh-CN') }}</td><td><span class="tag">{{ historyScopeLabels[event.scope] || event.scope }}</span></td><td><template v-if="event.subject"><button class="code-link" :aria-label="`快速查看 ${event.subject.code}`" @click="previewItem(event.subject)">{{event.subject.code}}</button><br>{{event.subject.name}}</template><span v-else>{{ entityLabels[event.entity_type] || event.entity_type }}</span></td><td><div v-for="(path,pathIndex) in event.paths" :key="pathIndex" class="history-path"><template v-for="(pathItem,itemIndex) in path" :key="pathItem.id"><button class="code-link" :aria-label="`快速查看 ${pathItem.code}`" @click="previewItem(pathItem)">{{pathItem.code}}</button><span>｜{{pathItem.name}}</span><span v-if="itemIndex<path.length-1"> → </span></template></div><span v-if="!event.paths?.length">—</span></td><td>{{ historyAction(event) }}</td><td><div v-if="event.changes?.length"><div v-for="change in event.changes" :key="change.field"><strong>{{ fieldLabels[String(change.field)] || change.field }}：</strong>{{ showChangeValue(change.before) }} → {{ showChangeValue(change.after) }}</div></div><span v-else>已记录该操作</span></td><td>{{ event.reason || '—' }}</td></tr></tbody></table></div><div v-if="!history.length" class="empty">暂无变更记录</div></div>
      </template>
    </section>
    <section v-else class="card empty">从左侧选择一条物料查看详情</section>
  </div>

  <PathAlternativeEditor v-if="pathEditor&&selected" :owner-id="selected.id" :row="pathEditor" :readonly="!canModifyDetail||pathEditor.is_backup_path" @close="pathEditor=null" @saved="pathSaved" @preview="previewItem"/>
  <ItemQuickViewModal v-if="quickViewItem" :item="quickViewItem" :loading="quickViewLoading" :error="quickViewError" :full-href="quickViewHref" @close="closeQuickView" @preview="previewItem" @open-full="markExternalDetailOpened" />

  <div v-if="showEditReason" class="modal-mask"><form class="modal" role="dialog" aria-modal="true" aria-label="确认保存物料修改" @submit.prevent="saveEdit">
    <div class="modal-head"><h2>确认保存修改</h2><button type="button" aria-label="关闭" @click="showEditReason=false">×</button></div>
    <p class="subtitle">变更说明仅用于审计和变更记录，不属于物料基本信息。</p>
    <label>变更说明<input v-model="edit.reason" required autofocus placeholder="请说明本次修改原因" /></label>
    <div class="actions"><button type="button" class="btn secondary" @click="showEditReason=false">取消</button><button class="btn" :disabled="editSaving||!edit.reason.trim()">{{editSaving?'正在保存…':'确认保存'}}</button></div>
  </form></div>

  <div v-if="replaceLine" class="modal-mask"><form class="modal" role="dialog" aria-modal="true" aria-label="替换 BOM 组成" @submit.prevent="confirmReplace">
    <div class="modal-head"><h2>替换 BOM 组成</h2><button type="button" aria-label="关闭" @click="replaceLine=null">×</button></div>
    <div class="notice">当前物料：<strong>{{replaceLine.child.code}}｜{{replaceLine.child.name}}</strong><br/>替换只改变本行子物料，原数量 {{replaceLine.quantity}}、显示顺序和行备注均保持不变。</div>
    <label>替换为<ItemAutocomplete v-model="replaceForm.child_item_id" :items="allowedChildren" :has-more="hasMoreCandidateItems" :loading-more="candidateLoadingMore" :loaded-items="candidateLoadedCount" :total-items="allItemsTotal" :searching="candidateSearching" :search-total="candidateSearchTotal" label="替换目标物料" placeholder="输入编码、名称或规格搜索可用物料" @search="searchAllTypeCandidates" @load-more="loadMoreCandidateItems"/></label>
    <p v-if="replaceTarget" class="subtitle">将替换为：<strong>{{replaceTarget.code}}｜{{replaceTarget.name}}</strong>（{{labels[replaceTarget.item_type]}}）</p>
    <label>变更说明<input v-model="replaceForm.reason" required placeholder="记录本次替换原因"/></label>
    <p class="subtitle">如新物料不属于本行原替代组，保存时会自动清除该替代组并明确提示；存在直接重复或环路时系统会阻止保存。</p>
    <div class="actions"><button type="button" class="btn secondary" @click="replaceLine=null">取消</button><button class="btn" :disabled="replaceBusy||!replaceForm.child_item_id||!replaceForm.reason.trim()">{{replaceBusy?'正在替换…':'确认替换'}}</button></div>
  </form></div>

  <div v-if="showCreate" class="modal-mask"><form class="modal" @submit.prevent="create">
    <div class="modal-head"><h2>新建{{ labels[type] }}</h2><button type="button" aria-label="关闭" @click="showCreate=false">×</button></div>
    <div class="card" style="margin-bottom:14px"><h3>复制已有{{labels[type]}}（可选）</h3><p class="subtitle">只显示同类型物料；选择后自动填充档案、组成和编码规则。可点击输入框右侧“×”清除后重新选择。</p><div class="toolbar" style="margin-top:10px;margin-bottom:0"><ItemAutocomplete v-model="copySourceId" :items="copyCandidates" :has-more="hasMoreCandidateItems" :loading-more="candidateLoadingMore" :loaded-items="candidateLoadedCount" :total-items="allItemsTotal" :searching="candidateSearching" :search-total="candidateSearchTotal" clearable :label="`选择要复制的${labels[type]}`" placeholder="输入编码、名称或规格，自动搜索全部物料" @search="searchCurrentTypeCandidates" @load-more="loadMoreCandidateItems"/><button type="button" class="btn secondary" :disabled="!copySourceId||copyBusy" @click="applyItemCopy">{{copyBusy?'正在复制…':'复制并自动填充'}}</button></div></div>
    <div v-if="largeCategories.length&&!(type==='material'&&!form.is_formally_imported)" class="card" style="margin-bottom:14px"><h3>按编码规则逐步选择</h3><div class="form-grid"><label>大类<select v-model="guide.large" @change="guide.small='';guide.ruleId=0"><option value="">全部大类</option><option v-for="option in largeCategories" :key="option.value" :value="option.value">{{ option.value }} | {{ option.code }}</option></select></label><label>小类<select v-model="guide.small" @change="guide.ruleId=0"><option value="">请选择</option><option v-for="option in smallCategories" :key="option.value" :value="option.value">{{ option.value }} | {{ option.code }}</option></select></label><label class="span-2">编码规则<select v-model="guide.ruleId" @change="recommend"><option :value="0">请选择规则</option><option v-for="rule in filteredRules" :key="rule.id" :value="rule.id">{{ rule.material_attribute || rule.small_category || '编码规则' }}｜{{ rule.pattern }}</option></select></label></div></div>
    <div class="form-grid">
      <label v-if="type==='material'">导入状态<select v-model="form.is_formally_imported"><option :value="true">正式导入</option><option :value="false">未正式导入</option></select><small v-if="!form.is_formally_imported" class="field-help">使用 99 专属号段；最终编号在提交事务时自动分配</small></label>
      <label>系统物料编码<template v-if="type==='material'&&!form.is_formally_imported"><input :value="unofficialEstimate||form.code" readonly aria-label="未正式原材料预计编号"/><small class="field-help">预计编号，不提前占号；多人同时提交时可能自动顺延</small></template><template v-else-if="selectedCodeRule"><span class="code-rule-input"><span class="code-rule-prefix" data-testid="code-rule-prefix" title="该部分由所选编码规则固定">{{selectedRulePrefix}}</span><input v-model="selectedRuleSuffix" required inputmode="decimal" :placeholder="selectedRuleSuffixPlaceholder" aria-label="系统物料编码后缀" /></span><small class="field-help">固定前缀不可修改；完整编码：<strong data-testid="full-material-code">{{form.code}}</strong></small></template><input v-else v-model="form.code" required :placeholder="type==='material'?'例如 10.1001.01':type==='machine'?'例如 00.001.01':type==='unit'?'例如 03.001.01':'例如 05.101.01'" /></label>
      <label>辅助索引码<input v-model="form.auxiliary_code" /></label><div v-if="form.code" class="span-2 code-check" :class="{error:(form.is_formally_imported&&codeCheck?.exists)||codeCheck?.valid===false,success:codeCheck?.valid&&(!form.is_formally_imported||!codeCheck?.exists)}"><strong v-if="codeChecking">正在检查编码…</strong><template v-else-if="codeCheck"><strong>{{codeCheck.message}}</strong><span v-if="codeCheck.maximum">{{guide.ruleId?'当前规则最大已存在':'当前系列最大已存在'}}：{{codeCheck.maximum.code}}</span><div v-if="codeCheck.duplicate_items?.length"><small v-for="item in codeCheck.duplicate_items" :key="item.id">重复候选：{{item.code}}｜{{item.name}}｜{{item.specification||'无规格'}}</small></div><div v-if="codeCheck.valid" class="toolbar"><button v-if="codeCheck.next_body_code&&codeCheck.next_body_code!==form.code" type="button" class="btn secondary small" @click="useCodeSuggestion(codeCheck.next_body_code)">使用下一主体 {{codeCheck.next_body_code}}</button><button v-if="codeCheck.next_version_code&&codeCheck.next_version_code!==form.code" type="button" class="btn secondary small" @click="useCodeSuggestion(codeCheck.next_version_code)">使用同主体下一版本 {{codeCheck.next_version_code}}</button></div></template></div>
      <label>名称<input v-model="form.name" required /></label><label>规格型号<input v-model="form.specification" /></label><label>单位<input v-model="form.unit" required /></label><label v-if="type==='material'">来源<select v-model="form.source_type"><option value="purchased">外购</option><option value="outsourced">外协</option><option value="self_made">自制</option></select></label><label v-else>初始状态<select v-model="form.status"><option value="trial">试制</option><option value="active">在用</option></select></label>
      <label v-if="type==='material'">上一版本名称<input v-model="form.previous_version_name" /></label><label v-if="type==='material'">发票名称<input v-model="form.invoice_name" /></label><label v-if="type==='material'">材料属性<input v-model="form.material_attribute" /></label><label v-if="type==='material'">关键器件码<input v-model="form.key_component_code" list="key-component-code-options" maxlength="5" pattern="[A-Za-z0-9]{3}\.[A-Za-z0-9]" placeholder="例如 F33.A，可留空" @input="queueKeyComponentCheck(form.key_component_code)"/><small class="field-help">三位字母或数字 + 点号 + 一位字母或数字；自动转大写，允许重复</small><small v-if="keyCodeCheck">{{keyCodeCheck.message}}<span v-for="item in keyCodeCheck.duplicate_items||[]" :key="item.id"><br/>{{item.code}}｜{{item.name}}</span></small></label><label v-if="type==='machine'">机型<input v-model="form.machine_model" list="machine-model-options" placeholder="可选已有机型或手工新增" /></label><label class="span-2">备注<textarea v-model="form.remark" rows="2" /></label>
    </div>
      <div v-if="type==='material'&&['outsourced','self_made'].includes(form.source_type)" class="card" style="margin-top:14px"><h3>组装来源（可稍后完善）</h3><p class="subtitle">外协、自制原材料均允许先作为叶子保存，后续再维护下级组成；只有正式导入原材料可被选作子项。</p><div class="toolbar"><ItemAutocomplete v-model="componentDraft.child_item_id" :items="allItems.filter(x=>x.item_type==='material'&&x.status!=='disabled'&&x.is_formally_imported!==false)" :has-more="hasMoreCandidateItems" :loading-more="candidateLoadingMore" :loaded-items="candidateLoadedCount" :total-items="allItemsTotal" :searching="candidateSearching" :search-total="candidateSearchTotal" label="选择原材料" placeholder="输入编码、名称或规格，自动搜索全部物料" @search="searchMaterialCandidates" @load-more="loadMoreCandidateItems"/><label>组成数量<input v-model="componentDraft.quantity" type="number" min="0.000001" step="any" style="width:100px"/></label><button type="button" class="btn secondary small" @click="addComponent">加入</button></div><p v-for="(row,index) in form.components" :key="index">{{ row.child.code }} {{ row.child.name }} × {{ row.quantity }} <button type="button" class="link-button" style="color:#dc2626" @click="form.components.splice(index,1)">移除</button></p></div>
      <div v-if="type==='semi_finished'" class="card" style="margin-top:14px"><h3>下级组成（可选）</h3><p class="subtitle">加入至少一个“半成品”子项后，创建结果会自动标记为“组合半成品”；无需另选标签。也可只加入原材料，或创建后再到 BOM 编辑维护。</p><div class="toolbar"><ItemAutocomplete v-model="componentDraft.child_item_id" :items="createAllowedChildren" :has-more="hasMoreCandidateItems" :loading-more="candidateLoadingMore" :loaded-items="candidateLoadedCount" :total-items="allItemsTotal" :searching="candidateSearching" :search-total="candidateSearchTotal" label="选择下级组成" placeholder="搜索半成品或原材料" @search="searchAllTypeCandidates" @load-more="loadMoreCandidateItems"/><label>组成数量<input v-model="componentDraft.quantity" type="number" min="0.000001" step="any" style="width:100px"/></label><label>行备注<input v-model="componentDraft.line_remark" placeholder="可选"/></label><button type="button" class="btn secondary small" :disabled="!componentDraft.child_item_id" @click="addComponent">加入组成</button></div><p v-if="form.components.length" class="subtitle">复制的 BOM 组成（{{form.components.length}}），包含复制项及本次新增项</p><p v-for="(row,index) in form.components" :key="index"><span class="tag">{{labels[row.child.item_type]}}</span> <strong>{{ row.child.code }}</strong> {{ row.child.name }} × {{ row.quantity }}<span v-if="row.line_remark">｜{{row.line_remark}}</span> <button type="button" class="link-button" style="color:#dc2626" @click="form.components.splice(index,1)">移除</button></p></div>
      <div v-if="type!=='material'&&type!=='semi_finished'&&form.components.length" class="card" style="margin-top:14px"><h3>复制的 BOM 组成（{{form.components.length}}）</h3><p class="subtitle">以下组成会在创建时一并复制；请核对编码、名称和数量，也可以移除不需要的行。</p><p v-for="(row,index) in form.components" :key="index"><strong>{{ row.child.code }}</strong> {{ row.child.name }} × {{ row.quantity }} <button type="button" class="link-button" style="color:#dc2626" @click="form.components.splice(index,1)">移除</button></p></div>
    <label style="margin-top:14px"><span><input v-model="form.similarity_confirmed" type="checkbox" style="min-width:auto" /> 已检查并确认可能存在的高度相似物料</span></label>
    <label style="margin-top:12px">新建说明<input v-model="form.reason" required /></label><div class="actions"><button type="button" class="btn secondary" @click="showCreate=false">取消</button><button class="btn" :disabled="codeChecking||!codeCheck?.valid||(form.is_formally_imported&&codeCheck.exists)">创建物料</button></div>
  </form></div>
  <datalist id="machine-model-options"><option v-for="model in machineModels" :key="model" :value="model"/><option value="R60"/><option value="Y60"/><option value="T65"/></datalist>
  <datalist id="key-component-code-options"><option v-for="value in keyComponentCodes" :key="value" :value="value"/></datalist>
  <div v-if="showPromote" class="modal-mask"><form class="modal" @submit.prevent="promoteMaterial">
    <div class="modal-head"><h2>转为正式导入</h2><button type="button" aria-label="关闭" @click="showPromote=false">×</button></div>
    <div class="notice">来源 {{detail?.code}} 将永久封存；系统会创建一条新的正式原材料，复制当前档案和 {{detail?.components?.length||0}} 条直接组成。全部操作成功后才提交。</div>
    <div class="card"><h3>重新选择正式编码规则</h3><div class="form-grid"><label>大类<select v-model="promoteGuide.large" @change="promoteGuide.small='';promoteGuide.ruleId=0"><option value="">请选择大类</option><option v-for="option in promoteLargeCategories" :key="option.value" :value="option.value">{{option.value}} | {{option.code}}</option></select></label><label>小类<select v-model="promoteGuide.small" @change="promoteGuide.ruleId=0"><option value="">请选择小类</option><option v-for="option in promoteSmallCategories" :key="option.value" :value="option.value">{{option.value}} | {{option.code}}</option></select></label><label class="span-2">编码规则<select v-model="promoteGuide.ruleId" required @change="recommendPromote"><option :value="0">请选择规则</option><option v-for="rule in promoteRules" :key="rule.id" :value="rule.id">{{rule.material_attribute||rule.small_category||'编码规则'}}｜{{rule.pattern}}</option></select></label></div></div>
    <div class="form-grid"><label>正式系统物料编码<input v-model="promoteForm.code" required /></label><label>名称<input v-model="promoteForm.name" required/></label><label>规格型号<input v-model="promoteForm.specification"/></label><label>来源<select v-model="promoteForm.source_type"><option value="purchased">外购</option><option value="outsourced">外协</option><option value="self_made">自制</option></select></label><label>单位<input v-model="promoteForm.unit" required/></label><label>辅助索引码<input v-model="promoteForm.auxiliary_code"/></label><label>材料属性<input v-model="promoteForm.material_attribute"/></label><label>关键器件码<input v-model="promoteForm.key_component_code" list="key-component-code-options" maxlength="5" pattern="[A-Za-z0-9]{3}\.[A-Za-z0-9]" placeholder="可留空" @input="queueKeyComponentCheck(promoteForm.key_component_code,detail?.id)"/><small v-if="keyCodeCheck">{{keyCodeCheck.message}}<span v-for="item in keyCodeCheck.duplicate_items||[]" :key="item.id"><br/>{{item.code}}｜{{item.name}}</span></small></label><label>发票名称<input v-model="promoteForm.invoice_name"/></label><label>上一版本名称<input v-model="promoteForm.previous_version_name"/></label><label class="span-2">备注<textarea v-model="promoteForm.remark" rows="2"/></label></div>
    <div v-if="promoteChecking" class="notice">正在检查正式编码…</div><div v-else-if="promoteCheck" class="notice" :class="{error:!promoteCheck.valid||promoteCheck.exists}"><strong>{{promoteCheck.message}}</strong><div v-if="promoteCheck.conflict_item">冲突：{{promoteCheck.conflict_item.code}}｜{{promoteCheck.conflict_item.name}}</div><div class="toolbar"><button v-if="promoteCheck.next_body_code" type="button" class="btn secondary small" @click="promoteForm.code=promoteCheck.next_body_code">使用下一主体 {{promoteCheck.next_body_code}}</button><button v-if="promoteCheck.next_version_code" type="button" class="btn secondary small" @click="promoteForm.code=promoteCheck.next_version_code">使用下一版本 {{promoteCheck.next_version_code}}</button></div></div>
    <label><span><input v-model="promoteForm.similarity_confirmed" type="checkbox" style="min-width:auto"/> 已检查并确认可能存在的高度相似正式物料，仍创建新物料</span></label>
    <label>变更说明<input v-model="promoteForm.reason" required placeholder="说明转为正式导入的原因" /></label>
    <div class="actions"><button type="button" class="btn secondary" @click="showPromote=false">取消</button><button class="btn" :disabled="promoteBusy||promoteChecking||!promoteGuide.ruleId||!promoteCheck?.valid||promoteCheck.exists||!promoteForm.reason.trim()">{{promoteBusy?'正在转正式…':'创建正式物料并封存来源'}}</button></div>
  </form></div>
</template>
