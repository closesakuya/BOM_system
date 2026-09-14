<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { api, download } from '../api'
import { sourceLabels, itemTypeLabels } from '../labels'

type Row = { id: number; batch_id: number; row_number: number; payload: Record<string,any>; status: string; error_message?: string; similarity: any[] }
type Rule = { id:number; item_type:string; large_category?:string; small_category?:string; material_attribute?:string; prefix:string; pattern:string; active:boolean }
type CodeCheck = {valid:boolean;exists:boolean;message:string;duplicate_items?:any[];next_body_code?:string;next_version_code?:string}

const file = ref<File | null>(null)
const batch = ref<any>(null)
const rows = ref<Row[]>([])
const confirmed = ref<number[]>([])
const rules = ref<Rule[]>([])
const keyComponentCodes = ref<string[]>([])
const error = ref('')
const message = ref('')
const busy = ref(false)
const editingRow = ref<Row | null>(null)
const editBusy = ref(false)
const codeChecking = ref(false)
const codeCheck = ref<CodeCheck | null>(null)
let codeTimer: number | undefined
const edit = reactive<any>({
  item_type:'material', status:null, machine_model:'', code_input:null, auto_code:false, alias_errors:[], code:'', code_rule_id:0, large_category:'', small_category:'', auxiliary_code:'', name:'',
  specification:'', source_type:'purchased', unit:'pcs', remark:'', previous_version_name:'',
  invoice_name:'', material_attribute:'', key_component_code:'', historical_item_code:'', is_formally_imported:true,
})

const activeRows = computed(() => rows.value.filter(row => !['cancelled','imported'].includes(row.status)))
const invalidRows = computed(() => activeRows.value.filter(row => row.status === 'error'))
const unconfirmedRed = computed(() => activeRows.value.filter(row => row.status === 'red' && !confirmed.value.includes(row.id)))
const canCommit = computed(() => !!activeRows.value.length && !invalidRows.value.length && !unconfirmedRed.value.length && !busy.value)
const largeCategories = computed(() => [...new Set(rules.value.filter(rule=>rule.item_type===edit.item_type&&rule.active&&rule.large_category).map(rule=>rule.large_category!))])
const smallCategories = computed(() => [...new Set(rules.value.filter(rule=>rule.item_type===edit.item_type&&rule.active&&(!edit.large_category||rule.large_category===edit.large_category)&&rule.small_category).map(rule=>rule.small_category!))])
const filteredRules = computed(() => rules.value.filter(rule=>rule.item_type===edit.item_type&&rule.active&&(!edit.large_category||rule.large_category===edit.large_category)&&(!edit.small_category||rule.small_category===edit.small_category)))

async function preview() {
  if (!file.value) return
  busy.value = true; error.value = ''; message.value = ''
  const form = new FormData(); form.append('file', file.value)
  try {
    const [result, ruleRows, keyCodes] = await Promise.all([
      api<any>('/imports/materials/preview', { method: 'POST', body: form }),
      api<Rule[]>('/code-rules'), api<string[]>('/key-component-codes'),
    ])
    batch.value = result.batch; rows.value = result.rows; rules.value = ruleRows; keyComponentCodes.value = keyCodes
    confirmed.value = []
  } catch (event) { error.value = (event as Error).message } finally { busy.value = false }
}
async function refreshBatch() {
  if (!batch.value) return
  const refreshed = await api<any>(`/imports/${batch.value.id}`)
  rows.value = refreshed.rows; batch.value = refreshed.batch
}
async function commit() {
  if (!batch.value || !canCommit.value) return
  busy.value = true; error.value = ''
  try {
    const result = await api<any>(`/imports/${batch.value.id}/commit`, {
      method: 'POST',
      body: JSON.stringify({ row_ids: activeRows.value.map(row=>row.id), similarity_confirmed_row_ids: confirmed.value, reason: '确认整批导入物料' }),
    })
    message.value = `整批成功创建 ${result.created.length} 条物料`
    await refreshBatch()
  } catch (event) {
    error.value = (event as Error).message
    try { await refreshBatch() } catch { /* Preserve the original submission error. */ }
  } finally { busy.value = false }
}
function chooseFile(event: Event) { file.value = (event.target as HTMLInputElement).files?.[0] || null }
function openEdit(row:Row){editingRow.value=row;Object.assign(edit,{code:'',code_rule_id:0,large_category:'',small_category:'',auxiliary_code:'',historical_item_code:'',name:'',specification:'',source_type:'purchased',unit:'pcs',remark:'',previous_version_name:'',invoice_name:'',material_attribute:'',key_component_code:'',is_formally_imported:true,...row.payload});codeCheck.value=null;queueCodeCheck()}
function closeEdit(){editingRow.value=null;codeCheck.value=null}
function queueCodeCheck(){if(codeTimer)window.clearTimeout(codeTimer);codeCheck.value=null;if(!editingRow.value||!String(edit.code||'').trim())return;if(!edit.is_formally_imported){codeCheck.value={valid:true,exists:false,message:'提交时分配 99 编号'};codeChecking.value=false;return;}codeChecking.value=true;codeTimer=window.setTimeout(async()=>{try{const rule=edit.code_rule_id?`&code_rule_id=${edit.code_rule_id}`:'';codeCheck.value=await api<CodeCheck>(`/items/import-code-preview?code=${encodeURIComponent(String(edit.code_input||edit.code).trim())}&item_type=${edit.item_type}&is_formally_imported=${edit.is_formally_imported}${rule}`)}catch(event){codeCheck.value={valid:false,exists:false,message:(event as Error).message}}finally{codeChecking.value=false}},250)}
async function changeImportStatus(){if(!edit.is_formally_imported){if(edit.code&&!String(edit.code).startsWith('99.'))edit.historical_item_code=edit.code;const preview=await api<{estimated_code:string}>('/items/unofficial-code-preview');edit.code=preview.estimated_code;edit.code_rule_id=0;edit.large_category='';edit.small_category=''}else if(String(edit.code).startsWith('99.'))edit.code='';queueCodeCheck()}
async function chooseRule(){const rule=rules.value.find(row=>row.id===Number(edit.code_rule_id));if(!rule)return;edit.large_category=rule.large_category||'';edit.small_category=rule.small_category||'';edit.material_attribute=rule.material_attribute||edit.material_attribute;queueCodeCheck()}
async function saveEdit(){if(!editingRow.value||!codeCheck.value?.valid||(edit.is_formally_imported&&codeCheck.value.exists))return;editBusy.value=true;error.value='';try{await api(`/imports/${editingRow.value.batch_id}/rows/${editingRow.value.id}`,{method:'PATCH',body:JSON.stringify({...edit,code_rule_id:edit.is_formally_imported?Number(edit.code_rule_id)||null:null,cancelled:false})});const rowNumber=editingRow.value.row_number;await refreshBatch();message.value=`第 ${rowNumber} 行已重新校验`;closeEdit()}catch(event){error.value=(event as Error).message}finally{editBusy.value=false}}
async function cancelRow(row:Row){if(!confirm(`确认取消 Excel 第 ${row.row_number} 行？该行不会导入。`))return;try{await api(`/imports/${row.batch_id}/rows/${row.id}`,{method:'PATCH',body:JSON.stringify({cancelled:true})});confirmed.value=confirmed.value.filter(id=>id!==row.id);await refreshBatch();message.value=`已取消第 ${row.row_number} 行`}catch(event){error.value=(event as Error).message}}
onBeforeUnmount(()=>{if(codeTimer)window.clearTimeout(codeTimer)})
</script>

<template>
  <header class="page-head"><div><h1>物料 Excel 导入</h1><p class="subtitle">先预览并逐行校正，所有未取消行校验通过后一次性原子提交</p></div></header>
  <div v-if="error" class="notice error" role="alert">{{ error }}</div><div v-if="message" class="notice">{{ message }}</div>
  <section class="card">
    <div class="toolbar"><input type="file" accept=".xlsx,.xlsm" aria-label="选择原材料Excel" @change="chooseFile"/><button class="btn" :disabled="!file||busy" @click="preview">{{ busy?'正在预检…':'预览导入' }}</button><span class="subtitle">外购、外协和自制均可先导入；外协/自制组成可稍后完善</span></div>
    <template v-if="batch"><div class="toolbar"><span class="tag">批次 #{{ batch.id }}</span><span>就绪 {{ batch.stats.ready||0 }}</span><span>提示 {{ (batch.stats.yellow||0)+(batch.stats.red||0) }}</span><span>错误 {{ batch.stats.error||0 }}</span><span>已取消 {{batch.stats.cancelled||0}}</span><button class="btn secondary small" @click="download(`/imports/${batch.id}/report`,`导入批次-${batch.id}-结果.xlsx`)">下载结果</button></div>
      <div v-if="invalidRows.length" class="notice error">仍有 {{invalidRows.length}} 行错误。请点击“编辑”修正，或“取消此行”；系统不会部分导入。</div>
      <div class="table-wrap"><table><thead><tr><th>Excel 行</th><th>物料类型</th><th>原输入编码</th><th>预览／最终编码</th><th>历史物料号</th><th>名称</th><th>属性</th><th>正式状态</th><th>状态</th><th>说明/相似项</th><th>操作</th></tr></thead><tbody><tr v-for="row in rows" :key="row.id"><td>{{ row.row_number }}</td><td>{{itemTypeLabels[row.payload.item_type]}}</td><td>{{ row.payload.code_input||'—' }}</td><td>{{ row.payload.code }}</td><td>{{row.payload.historical_item_code||'—'}}</td><td>{{ row.payload.name }}</td><td>{{ sourceLabels[row.payload.source_type] || row.payload.source_type }}</td><td>{{row.payload.is_formally_imported===false?'未正式导入':'正式导入'}}</td><td><span class="tag" :class="{warn:['yellow','red'].includes(row.status),red:row.status==='error'}">{{ {ready:'待提交',yellow:'相似提示',red:'高度相似',error:'错误',imported:'已导入',cancelled:'已取消'}[row.status] || row.status }}</span></td><td>{{ row.error_message }}<div v-if="row.status==='red'"><label><span><input v-model="confirmed" type="checkbox" :value="row.id" style="min-width:auto"/> 确认仍创建</span></label></div><small v-for="candidate in row.similarity" :key="candidate.item.id">{{ candidate.item.code }} {{ candidate.item.name }} ({{ candidate.full_score }}%)<br/></small></td><td><template v-if="!['imported','cancelled'].includes(row.status)"><button class="btn secondary small" @click="openEdit(row)">编辑</button> <button class="btn danger small" @click="cancelRow(row)">取消此行</button></template></td></tr></tbody></table></div>
      <div class="actions"><button class="btn" :disabled="!canCommit" @click="commit">一次性提交 {{ activeRows.length }} 行</button><span v-if="unconfirmedRed.length" class="subtitle">还有 {{unconfirmedRed.length}} 条高度相似行待确认</span></div>
    </template>
  </section>

  <datalist id="import-key-code-options"><option v-for="value in keyComponentCodes" :key="value" :value="value"/></datalist>
  <div v-if="editingRow" class="modal-mask"><form class="modal" @submit.prevent="saveEdit">
    <div class="modal-head"><h2>编辑 Excel 第 {{editingRow.row_number}} 行</h2><button type="button" aria-label="关闭" @click="closeEdit">×</button></div>
    <div class="form-grid"><label>物料类型<select v-model="edit.item_type" @change="edit.code_rule_id=0;edit.large_category='';edit.small_category='';edit.source_type=edit.item_type==='material'?'purchased':null;edit.status=edit.item_type==='material'?'active':'trial';queueCodeCheck()"><option value="material">原材料</option><option value="semi_finished">半成品</option><option value="unit">单元</option><option value="machine">整机</option></select></label><label>状态<select v-model="edit.status"><option value="active">在用</option><option v-if="edit.item_type!=='material'" value="trial">试制</option><option value="disabled">停用</option></select></label><label v-if="edit.item_type==='machine'">机型<input v-model="edit.machine_model"/></label>
      <label>导入状态<select v-model="edit.is_formally_imported" @change="changeImportStatus"><option :value="true">正式导入</option><option :value="false">未正式导入</option></select></label><label>系统物料编码<input v-model="edit.code" required :readonly="!edit.is_formally_imported" @input="edit.code_input=edit.code;queueCodeCheck()"/><small v-if="!edit.is_formally_imported">预计编号，提交时按整批行号分配最终 99 编号</small></label><label>历史物料号<input v-model="edit.historical_item_code"/></label>
      <template v-if="edit.is_formally_imported"><label>大类<select v-model="edit.large_category" @change="edit.small_category='';edit.code_rule_id=0"><option value="">请选择</option><option v-for="value in largeCategories" :key="value" :value="value">{{value}}</option></select></label><label>小类<select v-model="edit.small_category" @change="edit.code_rule_id=0"><option value="">请选择</option><option v-for="value in smallCategories" :key="value" :value="value">{{value}}</option></select></label><label class="span-2">编码规则<select v-model="edit.code_rule_id" @change="chooseRule"><option :value="0">不指定</option><option v-for="rule in filteredRules" :key="rule.id" :value="rule.id">{{rule.material_attribute||rule.small_category}}｜{{rule.pattern}}</option></select></label></template>
      <div v-if="codeChecking" class="notice span-2">正在检查编码…</div><div v-else-if="codeCheck" class="notice span-2" :class="{error:!codeCheck.valid||(edit.is_formally_imported&&codeCheck.exists)}">{{codeCheck.message}}<small v-for="item in codeCheck.duplicate_items||[]" :key="item.id">{{item.code}}｜{{item.name}}｜{{item.specification||'无规格'}}</small></div>
      <label>名称<input v-model="edit.name" required/></label><label>规格型号<input v-model="edit.specification"/></label><label v-if="edit.item_type==='material'">来源<select v-model="edit.source_type"><option value="purchased">外购</option><option value="outsourced">外协</option><option value="self_made">自制</option></select></label><label>单位<input v-model="edit.unit" required/></label><label>辅助索引码<input v-model="edit.auxiliary_code"/></label><label v-if="edit.item_type==='material'">关键器件码<input v-model="edit.key_component_code" list="import-key-code-options" maxlength="5" pattern="[A-Za-z0-9]{3}\.[A-Za-z0-9]" placeholder="可留空"/></label><label>材料属性<input v-model="edit.material_attribute"/></label><label>发票名称<input v-model="edit.invoice_name"/></label><label>上一版本名称<input v-model="edit.previous_version_name"/></label><label class="span-2">备注<textarea v-model="edit.remark" rows="2"/></label>
    </div>
    <div class="actions"><button type="button" class="btn secondary" @click="closeEdit">取消编辑</button><button class="btn" :disabled="editBusy||codeChecking||!codeCheck?.valid||(edit.is_formally_imported&&codeCheck.exists)">{{editBusy?'正在保存…':'保存并重新校验'}}</button></div>
  </form></div>
</template>
