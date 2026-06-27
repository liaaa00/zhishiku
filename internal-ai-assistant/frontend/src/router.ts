import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/login/index.vue'
import ChatView from './views/chat/index.vue'
import AdminView from './views/admin/index.vue'
import { useAuthStore } from './stores/auth'

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
  const auth = useAuthStore()
  const requiresAuth = Boolean(to.meta.requiresAuth)
  const requiresAdmin = Boolean(to.meta.requiresAdmin)

  if (to.path === '/login' && auth.isAuthenticated) return '/chat'
  if (requiresAuth && !auth.isAuthenticated) return '/login'
  if (requiresAdmin && !auth.isAdmin) return '/chat'

  return true
})

export default router
