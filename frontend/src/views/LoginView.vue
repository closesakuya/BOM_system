<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, setSession, type User } from '../api'

const router = useRouter()
const username = ref('admin')
const password = ref('admin123')
const error = ref('')
const busy = ref(false)
async function submit() {
  busy.value = true; error.value = ''
  try {
    const result = await api<{ access_token: string; user: User }>('/auth/login', {
      method: 'POST', body: JSON.stringify({ username: username.value, password: password.value }),
    })
    setSession(result.access_token, result.user)
    await router.push('/')
  } catch (event) { error.value = (event as Error).message } finally { busy.value = false }
}
</script>

<template>
  <div class="login-page">
    <section class="login-hero">
      <div class="brand-mark">B</div>
      <h1>让每一条物料关系清楚、可靠、可追溯</h1>
      <p>面向生产现场的 BOM V1.2。统一管理原材料、半成品、单元和整机，保留历史数据，并用清晰的技术 BOM 与生产 BOM 支撑日常工作。</p>
    </section>
    <section class="login-side">
      <form class="login-box" @submit.prevent="submit">
        <h1>登录系统</h1><p class="subtitle">使用分配给您的账户继续</p>
        <div v-if="error" class="notice error" role="alert">{{ error }}</div>
        <label>用户名<input v-model="username" name="username" autocomplete="username" required /></label>
        <label>密码<input v-model="password" name="password" type="password" autocomplete="current-password" required /></label>
        <button class="btn" :disabled="busy">{{ busy ? '正在登录…' : '登录' }}</button>
      </form>
    </section>
  </div>
</template>
