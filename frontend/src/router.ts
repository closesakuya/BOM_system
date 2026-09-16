import { createRouter, createWebHistory } from 'vue-router'
import { session, canVisit } from './api'
import LoginView from './views/LoginView.vue'
import DashboardView from './views/DashboardView.vue'
import ItemsView from './views/ItemsView.vue'
import ImportView from './views/ImportView.vue'
import MaintenanceView from './views/MaintenanceView.vue'
import CompareView from './views/CompareView.vue'
import RulesView from './views/RulesView.vue'
import AlternativesView from './views/AlternativesView.vue'
import AuditView from './views/AuditView.vue'
import UsersView from './views/UsersView.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/', component: DashboardView },
    { path: '/items/:type', component: ItemsView },
    { path: '/imports', component: ImportView },
    { path: '/maintenance', component: MaintenanceView },
    { path: '/compare', component: CompareView },
    { path: '/rules', component: RulesView },
    { path: '/alternatives', component: AlternativesView },
    { path: '/audit', component: AuditView },
    { path: '/users', component: UsersView },
  ],
})

router.beforeEach((to) => {
  if (!to.meta.public && !session.token) return '/login'
  if (!to.meta.public && !canVisit(to.path)) return '/'
  if (to.path === '/login' && session.token) return '/'
})
