import { createRouter, createWebHistory } from 'vue-router'
import LoginView from './views/login/index.vue'
import ChatView from './views/chat/index.vue'
import AdminView from './views/admin/index.vue'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/login', component: LoginView },
    { path: '/chat', component: ChatView },
    { path: '/admin', component: AdminView },
  ],
})
