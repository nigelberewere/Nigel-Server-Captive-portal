<template>
  <div class="container">
    <header class="flex justify-between items-center mb-8">
      <h1 class="brand-logo">Nigel<span>Server</span></h1>
      <button @click="logout" class="btn btn-secondary">Disconnect</button>
    </header>

    <div class="card mb-8">
      <h2 class="mb-4">Welcome to the Network</h2>
      <p class="text-muted">You are successfully connected. Below you can find links to the available local services.</p>
      
      <!-- Session info could be shown here -->
      <div class="mt-4 text-sm text-muted">
        <p><strong>Status:</strong> Authenticated</p>
      </div>
    </div>

    <h3 class="mb-4">Available Services</h3>
    <div class="services-grid">
      <div v-for="svc in services" :key="svc.id" class="card service-card" @click="goTo(svc.url)">
        <div class="icon-wrapper">
           <!-- Simple CSS icon fallback or icon library could be used -->
           <span class="icon">{{ svc.icon.charAt(0).toUpperCase() }}</span>
        </div>
        <h4>{{ svc.name }}</h4>
        <p class="text-sm text-muted mt-2">{{ svc.description }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const services = ref([])

onMounted(async () => {
  try {
    const res = await fetch('/api/hub/services')
    if (res.ok) {
      services.value = await res.json()
    }
  } catch (err) {
    console.error("Failed to load services")
  }
})

function goTo(url) {
  window.open(url, '_blank')
}

async function logout() {
  try {
    const urlParams = new URLSearchParams(window.location.search);
    const mac_address = urlParams.get('mac') || '';
    await fetch('/api/auth/logout', { 
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mac_address })
    })
  } catch (err) {}
  router.push('/login')
}
</script>

<style scoped>
.services-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(250px, 1fr));
  gap: 1.5rem;
}
.service-card {
  cursor: pointer;
  transition: transform 0.2s, border-color 0.2s;
  text-align: center;
}
.service-card:hover {
  transform: translateY(-4px);
  border-color: var(--accent-color);
}
.icon-wrapper {
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background-color: rgba(245, 158, 11, 0.1);
  color: var(--accent-color);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.5rem;
  font-weight: 600;
  margin: 0 auto 1rem auto;
}
</style>
