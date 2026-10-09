<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout, session, canVisit } from './api'
import { roleLabels } from './labels'

const route = useRoute()
const router = useRouter()
const loggedIn = computed(() => !!session.token)
const sidebarCollapsed = ref(localStorage.getItem('bom_sidebar_collapsed') === 'true')
function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
  localStorage.setItem('bom_sidebar_collapsed', String(sidebarCollapsed.value))
}
const links = [
  ['/', '工作台'], ['/items/material', '原材料'], ['/items/semi_finished', '半成品'],
  ['/items/unit', '单元'], ['/items/machine', '整机'], ['/imports', '物料导入'],
  ['/maintenance', '批量维护'], ['/compare', 'BOM 比较'], ['/alternatives', '选配替代'],
  ['/rules', '编码规则'], ['/audit', '变更日志'], ['/users', '账户管理'],
]
function signOut() { logout(); router.push('/login') }
const visibleLinks = computed(() => links.filter(link => canVisit(link[0])))
</script>

<template>
  <RouterView v-if="!loggedIn || route.path === '/login'" />
  <div v-else class="app-shell" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <aside class="sidebar">
      <button type="button" class="sidebar-toggle" :aria-label="sidebarCollapsed ? '展开菜单' : '收起菜单'" :title="sidebarCollapsed ? '展开菜单' : '收起菜单'" :aria-expanded="!sidebarCollapsed" aria-controls="sidebar-content" @click="toggleSidebar">
        <span aria-hidden="true">{{ sidebarCollapsed ? '☰' : '«' }}</span><span v-if="!sidebarCollapsed">收起菜单</span>
      </button>
      <div v-show="!sidebarCollapsed" id="sidebar-content" class="sidebar-content">
      <div class="brand"><span class="brand-mark">B</span><div><strong>BOM V1.2</strong><small>物料清单管理</small></div></div>
      <nav aria-label="主导航">
        <RouterLink v-for="link in visibleLinks" :key="link[0]" :to="link[0]">{{ link[1] }}</RouterLink>
      </nav>
      <div class="user-card">
        <strong>{{ session.user?.display_name }}</strong><small>{{ roleLabels[session.user?.role || ''] }}</small>
        <button class="link-button" @click="signOut">退出登录</button>
      </div>
      </div>
    </aside>
    <main class="main"><RouterView /></main>
  </div>
</template>
