import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/login/index.vue'
import ChatView from './views/chat/index.vue'
import AdminView from './views/admin/index.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView },
    { path: '/chat', component: ChatView, meta: { authOnly: true } },
    { path: '/admin', component: AdminView, meta: { adminOnly: true } },
  ],
})

router.beforeEach((to) => {
  const token = localStorage.getItem('token')
  if (to.meta.authOnly && !token) return '/login'
  if (!to.meta.adminOnly) return true
  if (!token) return '/login'

  try {
    const rawUser = localStorage.getItem('user')
    if (!rawUser) return '/chat'
    const user = JSON.parse(rawUser)
    return user?.is_admin ? true : '/chat'
  } catch {
    return '/chat'
  }
})

export default router
