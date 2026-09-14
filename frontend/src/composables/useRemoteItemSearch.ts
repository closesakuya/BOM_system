import { onBeforeUnmount, ref, type Ref } from 'vue'
import { api, type Item } from '../api'

type ItemPage = { total: number; items: Item[] }
type SearchFilters = Record<string, string | number | boolean | null | undefined>

export function useRemoteItemSearch(items: Ref<Item[]>, reportError?: (message: string) => void) {
  const searching = ref(false)
  const searchTotal = ref(-1)
  const results = ref<Item[]>([])
  let timer: number | undefined
  let request = 0
  let currentQuery = ''
  let currentFilters: SearchFilters = {}

  function search(query: string, filters: SearchFilters = {}) {
    if (timer) window.clearTimeout(timer)
    const requestId = ++request
    const term = query.trim()
    currentQuery = term
    currentFilters = { ...filters }
    results.value = []
    searchTotal.value = -1
    if (!term) {
      searching.value = false
      return
    }
    searching.value = true
    const capturedFilters = { ...filters }
    timer = window.setTimeout(async () => {
      const params = new URLSearchParams({ q: term, limit: '1000' })
      Object.entries(capturedFilters).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') params.set(key, String(value))
      })
      try {
        const response = await api<ItemPage>(`/items?${params}`)
        if (requestId !== request) return
        results.value = response.items
        searchTotal.value = response.total
        items.value = [...new Map([...items.value, ...response.items].map(item => [item.id, item])).values()]
          .sort((left, right) => left.code.localeCompare(right.code, 'zh-CN'))
      } catch (event) {
        if (requestId === request) reportError?.((event as Error).message)
      } finally {
        if (requestId === request) searching.value = false
      }
    }, 260)
  }

  function cancel() {
    if (timer) window.clearTimeout(timer)
    timer = undefined
    request += 1
    searching.value = false
    searchTotal.value = -1
    results.value = []
  }

  async function loadMore() {
    if (searching.value || !currentQuery || results.value.length >= searchTotal.value) return
    const requestId = request
    searching.value = true
    const params = new URLSearchParams({q:currentQuery, limit:'1000', offset:String(results.value.length)})
    Object.entries(currentFilters).forEach(([key,value])=>{if(value!==undefined&&value!==null&&value!=='')params.set(key,String(value))})
    try {
      const response=await api<ItemPage>(`/items?${params}`)
      if(requestId!==request)return
      results.value=[...results.value,...response.items]
      searchTotal.value=response.total
      items.value=[...new Map([...items.value,...response.items].map(item=>[item.id,item])).values()]
    } catch(event) { if(requestId===request)reportError?.((event as Error).message) }
    finally { if(requestId===request)searching.value=false }
  }

  onBeforeUnmount(cancel)
  return { searching, searchTotal, results, search, cancel, loadMore }
}
