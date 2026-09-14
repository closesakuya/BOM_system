import { reactive } from 'vue'

export type User = { id: number; username: string; display_name: string; department?: string; role: string; active: boolean }
export type Item = {
  id: number; item_type: string; code: string; name: string; specification?: string; source_type?: string;
  unit: string; status?: string; remark?: string; material_attribute?: string; requires_assembly: boolean; deleted_at?: string;
  auxiliary_code?: string; previous_version_name?: string; invoice_name?: string;
  key_component_code?: string; historical_item_code?: string; machine_model?: string; is_formally_imported: boolean;
  unofficial_status?: 'pending' | 'archived';
  promotion_trace?: { promoted_to?: Item; promoted_from: Item[] };
  is_combination?: boolean;
}

export const session = reactive<{ token: string; user: User | null }>({
  token: localStorage.getItem('bom_token') || '',
  user: JSON.parse(localStorage.getItem('bom_user') || 'null'),
})

export function setSession(token: string, user: User) {
  Object.keys(sessionStorage).filter(key => key.startsWith('bom_switch_')).forEach(key => sessionStorage.removeItem(key))
  session.token = token
  session.user = user
  localStorage.setItem('bom_token', token)
  localStorage.setItem('bom_user', JSON.stringify(user))
}

export function logout() {
  session.token = ''
  session.user = null
  localStorage.removeItem('bom_token')
  localStorage.removeItem('bom_user')
  Object.keys(sessionStorage).filter(key => key.startsWith('bom_switch_')).forEach(key => sessionStorage.removeItem(key))
}

export async function api<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (session.token) headers.set('Authorization', `Bearer ${session.token}`)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...options, headers })
  if (response.status === 401) logout()
  if (!response.ok) {
    let detail: unknown = `请求失败 (${response.status})`
    try { detail = (await response.json()).detail } catch { /* empty */ }
    const message = typeof detail === 'string' ? detail : JSON.stringify(detail)
    throw new Error(message)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export async function download(path: string, filename: string, options: RequestInit = {}) {
  return downloadFile(path, filename, options)
}

export async function apiWithImpactConfirmation<T = unknown>(path:string, options:RequestInit = {}):Promise<T> {
  try { return await api<T>(path,options) } catch(e) {
    let detail:any
    try { detail=JSON.parse((e as Error).message) } catch { throw e }
    if(!detail.affected_configurations?.length)throw e
    const affected=detail.affected_configurations.map((c:any)=>c.owner.code+' '+c.owner.name+'：'+(c.path_label||c.members.map((m:any)=>m.item.code+' '+m.item.name).join('、'))).join('\n')
    if(!window.confirm(detail.message+'\n'+affected+'\n确认清除以上配置并继续？'))throw new Error('已取消操作，数据未修改')
    if(options.method==='DELETE')return api<T>(path+(path.includes('?')?'&':'?')+'confirm_clear=true',options)
    return api<T>(path,{...options,body:JSON.stringify({...JSON.parse(String(options.body||'{}')),confirm_clear:true})})
  }
}

async function downloadFile(path: string, filename: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers)
  if (session.token) headers.set('Authorization', `Bearer ${session.token}`)
  if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json')
  const response = await fetch(`/api${path}`, { ...options, headers })
  if (!response.ok) throw new Error(`下载失败 (${response.status})`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  const disposition = response.headers.get('Content-Disposition') || ''
  const utf8Filename = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1]
  const regularFilename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
  try {
    anchor.download = utf8Filename ? decodeURIComponent(utf8Filename) : regularFilename || filename
  } catch {
    anchor.download = filename
  }
  anchor.click()
  URL.revokeObjectURL(url)
}
