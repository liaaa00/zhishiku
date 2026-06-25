import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/login/index.vue'
import ChatView from './views/chat/index.vue'
import AdminView from './views/admin/index.vue'

function currentUserIsAdmin() {
  try {
    const rawUser = localStorage.getItem('user')
    if (!rawUser) return false
    const user = JSON.parse(rawUser)
    return Boolean(user?.is_admin)
  } catch {
    return false
  }
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView, meta: { requiresAuth: false } },
    { path: '/chat', component: ChatView, meta: { requiresAuth: true } },
    { path: '/admin', component: AdminView, meta: { requiresAuth: true, requiresAdmin: true } },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  const requiresAuth = Boolean(to.meta.requiresAuth)
  const requiresAdmin = Boolean(to.meta.requiresAdmin)

  if (to.path === '/login' && token) return '/chat'
  if (requiresAuth && !token) return '/login'
  if (requiresAdmin && !currentUserIsAdmin()) return '/chat'

  return true
})

export default router
