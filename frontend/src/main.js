import { createApp } from 'vue'
import App from './App.vue'
import { createRouter, createWebHistory } from 'vue-router'
import './styles/main.css'

import LoginView from './views/LoginView.vue'
import HubView from './views/HubView.vue'
import AdminView from './views/AdminView.vue'
import AboutView from './views/AboutView.vue'

const routes = [
  { path: '/login', component: LoginView },
  { path: '/hub', component: HubView },
  { path: '/admin', component: AdminView },
  { path: '/about', component: AboutView },
  { path: '/:pathMatch(.*)*', redirect: '/login' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to) => {
  if (sessionStorage.getItem('nigel-password-change-required') === '1' && to.path !== '/login') {
    return '/login'
  }
})

const app = createApp(App)
app.use(router)
app.mount('#app')
