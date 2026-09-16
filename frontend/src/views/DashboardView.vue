<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { actionLabels, entityLabels, itemTypeLabels } from '../labels'

type Event = { id: number; action: string; entity_type: string; reason: string; created_at: string }
const data = ref<{ counts: Record<string, number>; bom_lines: number; disabled: number; recent_events: Event[] }>()
const error = ref('')
onMounted(async () => { try { data.value = await api('/dashboard') } catch (event) { error.value = (event as Error).message } })
const labels = itemTypeLabels
</script>

<template>
  <header class="page-head"><div><h1>工作台</h1><p class="subtitle">BOM 主数据与近期变更概览</p></div><span class="tag">V1.2</span></header>
  <div v-if="error" class="notice error">{{ error }}</div>
  <template v-if="data">
    <section class="grid grid-4">
      <article v-for="(count, type) in data.counts" :key="type" class="card stat"><span>{{ labels[String(type)] }}</span><strong>{{ count }}</strong></article>
    </section>
    <section class="grid grid-2" style="margin-top:16px">
      <article class="card stat"><span>BOM 关系</span><strong>{{ data.bom_lines }}</strong></article>
      <article class="card stat"><span>停用对象</span><strong>{{ data.disabled }}</strong></article>
    </section>
    <section class="card" style="margin-top:16px">
      <h2>最近变更</h2>
      <table><thead><tr><th>时间</th><th>动作</th><th>对象</th><th>原因</th></tr></thead>
        <tbody><tr v-for="event in data.recent_events" :key="event.id"><td>{{ new Date(event.created_at).toLocaleString() }}</td><td>{{ actionLabels[event.action] || event.action }}</td><td>{{ entityLabels[event.entity_type] || event.entity_type }}</td><td>{{ event.reason }}</td></tr></tbody>
      </table>
    </section>
  </template>
</template>
