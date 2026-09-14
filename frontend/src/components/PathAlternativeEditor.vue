<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, type Item } from '../api'
import ItemAutocomplete from './ItemAutocomplete.vue'
import { useRemoteItemSearch } from '../composables/useRemoteItemSearch'
const props = defineProps<{ ownerId: number; row: any; readonly?: boolean }>()
const emit = defineEmits<{ close: []; saved: []; preview: [item: Item] }>()
const items = ref<Item[]>([]), selected = ref(props.row.item.id), candidate = ref(0)
const mode = ref(props.row.local_configuration ? props.row.configuration_mode : 'inherit')
const members = ref<any[]>(props.row.members?.length ? props.row.members.map((m:any)=>({...m})) : [{item_id: props.row.item.id, item: props.row.item, market_share:'100.00'}])
const reason = ref(''), error = ref(''), busy = ref(false), affected = ref<any[]>([])
const { search, searching, searchTotal, results, loadMore } = useRemoteItemSearch(items, value=>error.value=value)
const candidates = computed(()=>items.value.filter(i=>i.item_type===props.row.item.item_type&&i.is_formally_imported&&i.status!=='disabled'&&!i.deleted_at))
function equalize() { let remaining=10000; members.value.forEach((m,i)=>{const value=i===members.value.length-1?remaining:Math.floor(10000/members.value.length);m.market_share=(value/100).toFixed(2);remaining-=value}) }
function add() { const item=items.value.find(i=>i.id===candidate.value);if(!item)return;if(members.value.some(m=>m.item_id===item.id)){error.value='该组件已在候选中';return}members.value.push({item_id:item.id,item,market_share:'0'});equalize();candidate.value=0;mode.value='custom' }
function redistribute(index:number) { const value=Number(members.value[index].market_share);if(!Number.isFinite(value)||value<0||value>100){error.value='占比应在 0–100 之间';return}let rest=10000-Math.round(value*100);const others=members.value.filter((_,i)=>i!==index);const total=others.reduce((s,m)=>s+Number(m.market_share),0);const initial=rest;others.forEach((m,i)=>{const share=i===others.length-1?rest:Math.round(initial*(total?Number(m.market_share)/total:1/others.length));m.market_share=(share/100).toFixed(2);rest-=share}) }
function remove(id:number){if(selected.value===id){error.value='请先切换当前选用项，再移除该候选';return}members.value=members.value.filter(m=>m.item_id!==id);equalize()}
async function save(confirmClear=false){busy.value=true;error.value='';try{await api(`/items/${props.ownerId}/path-alternatives`,{method:'PUT',body:JSON.stringify({line_path:props.row.line_path,mode:mode.value,selected_item_id:selected.value,members:members.value.map(m=>({item_id:m.item_id,market_share:m.market_share})),reason:reason.value,confirm_clear:confirmClear})});emit('saved')}catch(e){const msg=(e as Error).message;try{const detail=JSON.parse(msg);affected.value=detail.affected_configurations||[];error.value=detail.message||msg}catch{error.value=msg}}finally{busy.value=false}}
watch([mode,selected,members,reason],()=>affected.value=[],{deep:true})
</script>
<template><div class="modal-mask"><form class="modal" role="dialog" aria-modal="true" aria-label="路径选配配置" @submit.prevent="save()">
<div class="modal-head"><h2>{{readonly?'查看':'配置'}}路径选配</h2><button type="button" @click="emit('close')">×</button></div>
<p>{{row.item.code}}｜{{row.item.name}}，组成数量 {{row.quantity}}</p>
<p v-if="row.configuration_owner">{{row.local_configuration?'本物料配置':'继承自'}} {{row.configuration_owner.code}}｜{{row.configuration_owner.name}}</p>
<p v-if="error" class="notice error">{{error}}</p>
<label>配置方式<select v-model="mode" :disabled="readonly"><option value="inherit">继承下级配置</option><option value="custom">本路径自定义</option><option value="disabled">本路径禁用选配（固定组件）</option></select></label>
<p v-if="mode==='inherit'" class="subtitle">保存后跟随下级最新候选、占比和当前选用项。</p>
<div v-if="mode==='custom'&&!readonly" class="toolbar"><ItemAutocomplete v-model="candidate" :items="candidates" :searching="searching" :search-total="searchTotal" label="搜索选配组件" :has-more="searchTotal>results.length" :loading-more="searching" @load-more="loadMore" @search="q=>search(q,{item_type:row.item.item_type})"/><button type="button" class="btn secondary" @click="add">加入候选</button><button type="button" class="btn secondary" @click="equalize">平均分配</button></div>
<table><thead><tr><th>当前选用</th><th>编码／名称</th><th>规格型号</th><th>占比 %</th><th>操作</th></tr></thead><tbody><tr v-for="(member,index) in members" :key="member.item_id"><td><input v-model="selected" type="radio" :value="member.item_id" :disabled="readonly||mode==='inherit'"/></td><td><button type="button" class="code-link" @click="emit('preview',member.item)">{{member.item.code}}</button> {{member.item.name}}</td><td>{{member.item.specification||'—'}}</td><td><input v-model="member.market_share" type="number" min="0" max="100" step="0.01" :disabled="readonly||mode!=='custom'" @change="redistribute(index)" style="width:90px"/></td><td><button v-if="!readonly&&mode==='custom'" type="button" class="link-button" @click="remove(member.item_id)">移除</button></td></tr></tbody></table>
<label v-if="!readonly">变更说明<input v-model="reason" required/></label>
<div v-if="affected.length" class="notice"><p>以下路径配置将被清除：</p><p v-for="c in affected" :key="c.id">{{c.owner.code}} {{c.owner.name}}／{{c.path_label}}（当前：{{c.selected_item?.code}} {{c.selected_item?.name}}）</p><button type="button" class="btn danger" :disabled="busy" @click="save(true)">确认清除并保存</button></div>
<div class="actions"><button type="button" class="btn secondary" @click="emit('close')">{{readonly?'关闭':'取消'}}</button><button v-if="!readonly" class="btn" :disabled="busy||!reason.trim()">确认保存</button></div>
</form></div></template>
