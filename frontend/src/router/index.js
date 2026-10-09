import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'
import LoginView from '../views/LoginView.vue'
import RegisterView from '../views/RegisterView.vue'
import ChatView from '../views/ChatView.vue'
import DataView from '../views/DataView.vue'

const router = createRouter({ history: createWebHistory(), routes: [
  { path: '/', component: ChatView }, { path: '/login', component: LoginView, meta: { public: true } },
  { path: '/register', component: RegisterView, meta: { public: true } }, { path: '/data', component: DataView },
] })
router.beforeEach(async to => {
  const auth = useAuth()
  await auth.restore()
  if (!to.meta.public && !auth.user) return '/login'
  if (to.meta.public && auth.user) return '/'
  if (to.path === '/data' && !auth.user?.is_admin) return '/'
})
export default router
