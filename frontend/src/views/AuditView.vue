<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api, download, session } from '../api'
import { actionLabels, entityLabels } from '../labels'
const events=ref<any[]>([]);const entity=ref('');const message=ref('');const error=ref('')
async function load(){try{events.value=await api(`/audit?limit=500${entity.value?`&entity_type=${entity.value}`:''}`)}catch(event){error.value=(event as Error).message}}
async function backup(){try{const result=await api<any>('/backups',{method:'POST',body:JSON.stringify({label:'manual-ui'})});message.value=`备份已创建：${result.filename}`}catch(event){error.value=(event as Error).message}}
onMounted(load)
</script>
<template><header class="page-head"><div><h1>变更日志</h1><p class="subtitle">不可修改、不可删除的完整操作记录</p></div><div class="toolbar"><button class="btn secondary" @click="download('/audit/export','变更日志.xlsx')">导出日志</button><button v-if="session.user?.role==='admin'" class="btn" @click="backup">创建数据库备份</button></div></header><div v-if="error" class="notice error">{{error}}</div><div v-if="message" class="notice">{{message}}</div><section class="card"><div class="toolbar"><select v-model="entity"><option value="">全部对象</option><option value="item">物料</option><option value="bom_line">BOM 行</option><option value="import_batch">导入批次</option><option value="user">账户</option></select><button class="btn secondary" @click="load">筛选</button></div><div class="table-wrap"><table><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th><th>原因</th><th>批次</th></tr></thead><tbody><tr v-for="event in events" :key="event.id"><td>{{new Date(event.created_at).toLocaleString()}}</td><td>{{event.actor_id||'系统'}}</td><td>{{actionLabels[event.action]||event.action}}</td><td>{{entityLabels[event.entity_type]||event.entity_type}} #{{event.entity_id||'—'}}</td><td>{{event.reason}}</td><td>{{event.batch_key||'—'}}</td></tr></tbody></table></div></section></template>
