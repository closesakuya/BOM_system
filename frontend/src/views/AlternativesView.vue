<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, type Item } from '../api'
import ItemQuickViewModal from '../components/ItemQuickViewModal.vue'
const router=useRouter(), rows=ref<any[]>([]), query=ref(''), error=ref(''), quick=ref<any>(null)
const modes:Record<string,string>={custom:'本路径自定义',disabled:'本路径禁用'}
const filtered=computed(()=>rows.value.filter(row=>(row.owner.code+' '+row.owner.name+' '+row.members.map((m:any)=>m.item.code+' '+m.item.name).join(' ')).toLowerCase().includes(query.value.toLowerCase())))
onMounted(async()=>{try{rows.value=await api<any[]>('/path-alternatives')}catch(e){error.value=(e as Error).message}})
function open(row:any){router.push({path:'/items/'+row.owner.item_type,query:{id:row.owner.id,locate:'1',bom_path:row.line_path.join('/')}})}
async function preview(item:Item){try{quick.value=await api('/items/'+item.id)}catch(e){error.value=(e as Error).message}}
</script>
<template><header class="page-head"><div><h1>选配关系总览</h1><p class="subtitle">在 BOM 编辑完整层级树中创建选配；下级配置被上级继承，路径自定义和禁用仅作用于所属物料。</p></div></header>
<div v-if="error" class="notice error">{{error}}</div><section class="card"><label>搜索所属物料或候选<input v-model="query" placeholder="输入编码或名称"/></label>
<table><thead><tr><th>所属物料／路径</th><th>配置</th><th>当前选用</th><th>候选对比</th><th>操作</th></tr></thead><tbody><tr v-for="row in filtered" :key="row.id"><td><button class="code-link" @click="preview(row.owner)">{{row.owner.code}}</button> {{row.owner.name}}<div>{{row.path_label}}</div></td><td>{{modes[row.mode]}}</td><td>{{row.selected_item?.code}} {{row.selected_item?.name}}</td><td><details><summary>展开对比（{{row.members.length}} 项）</summary><table><thead><tr><th>物料</th><th>规格</th><th>占比</th></tr></thead><tbody><tr v-for="m in row.members" :key="m.item_id"><td><button class="code-link" @click="preview(m.item)">{{m.item.code}}</button> {{m.item.name}}</td><td>{{m.item.specification}}</td><td>{{m.market_share}}%</td></tr></tbody></table></details></td><td><button class="btn secondary small" @click="open(row)">查看／编辑所在 BOM</button></td></tr></tbody></table><p v-if="!filtered.length">暂无匹配配置，请在 BOM 层级树中添加。</p></section>
<ItemQuickViewModal v-if="quick" :item="quick" :full-href="router.resolve({path:'/items/'+quick.item_type,query:{id:quick.id,locate:'1'}}).href" @close="quick=null" @preview="preview"/>
</template>
