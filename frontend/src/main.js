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

const app = createApp(App)
app.use(router)
app.mount('#app')
