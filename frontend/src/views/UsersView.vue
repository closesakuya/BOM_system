<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { api, session, type User } from '../api'
import { roleLabels } from '../labels'
const rows = ref<User[]>([]), error = ref(''), message = ref(''), editing = ref<User | null>(null)
const form = reactive({ username: '', password: '', display_name: '', department: '', role: 'guest', active: true })
async function load() { rows.value = await api('/users') }
function edit(user: User) {
  editing.value = user
  Object.assign(form, user, { password: '' })
  error.value = ''; message.value = ''
}
async function save() {
  if (!editing.value) return
  try {
    const body: any = { username: form.username, display_name: form.display_name, department: form.department, role: form.role, active: form.active }
    if (form.password) body.password = form.password
    const updated = await api<User>('/users/' + editing.value.id, { method: 'PATCH', body: JSON.stringify(body) })
    if (updated.id === session.user?.id) { session.user = updated; localStorage.setItem('bom_user', JSON.stringify(updated)) }
    editing.value = null; form.password = ''; message.value = '账户已更新；密码仅保存哈希，不可查看原密码。'
    await load()
  } catch (event) { error.value = (event as Error).message }
}
onMounted(async () => { try { await load() } catch (e) { error.value = (e as Error).message } })
</script>
<template>
  <header class="page-head"><div><h1>账户管理</h1><p class="subtitle">管理员、研发、生产、访客四种角色；无需注册</p></div></header>
  <div v-if="error" class="notice error">{{error}}</div><div v-if="message" class="notice">{{message}}</div>
  <section class="card"><table><thead><tr><th>用户名</th><th>名称</th><th>角色</th><th>状态</th><th>操作</th></tr></thead>
    <tbody><tr v-for="user in rows" :key="user.id"><td>{{user.username}}</td><td>{{user.display_name}}</td><td>{{roleLabels[user.role] || user.role}}</td><td>{{user.active?'启用':'停用'}}</td><td><button class="btn secondary small" @click="edit(user)">编辑 / 重置密码</button></td></tr></tbody></table></section>
  <div v-if="editing" class="modal-mask"><form class="modal" @submit.prevent="save"><div class="modal-head"><h2>编辑账户</h2><button type="button" aria-label="关闭" @click="editing=null">×</button></div>
    <label>用户名<input v-model="form.username" required minlength="3"/></label><label>显示名称<input v-model="form.display_name" required/></label>
    <label>角色<select v-model="form.role" :disabled="editing.id===session.user?.id"><option value="admin">管理员</option><option value="dev">研发</option><option value="product">生产</option><option value="finance">财务</option><option value="guest">访客</option></select></label>
    <label>状态<select v-model="form.active" :disabled="editing.id===session.user?.id"><option :value="true">启用</option><option :value="false">停用</option></select></label>
    <label>新密码<input v-model="form.password" type="password" autocomplete="new-password" minlength="6" placeholder="留空则不修改密码"/></label>
    <div class="actions"><button type="button" class="btn secondary" @click="editing=null">取消</button><button class="btn">保存</button></div>
  </form></div>
</template>
