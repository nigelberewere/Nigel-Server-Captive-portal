<template>
  <div class="container">
    <header class="flex justify-between items-center mb-8">
      <h1 class="brand-logo">Nigel<span>Admin</span></h1>
      <button @click="logout" class="btn btn-secondary">Logout</button>
    </header>

    <div class="flex gap-4 mb-8">
      <div class="card flex-1">
        <h3 class="text-muted">Connected Devices</h3>
        <p class="text-2xl mt-2">{{ devices.length }}</p>
      </div>
      <div class="card flex-1">
        <h3 class="text-muted">Active Users</h3>
        <p class="text-2xl mt-2">{{ activeUsersCount }}</p>
      </div>
    </div>

    <div class="card">
      <div class="flex justify-between items-center mb-4">
        <h2>Live Device Monitor</h2>
        <button class="btn btn-secondary" @click="fetchDevices">Refresh</button>
      </div>
      
      <div class="table-responsive">
        <table class="w-full text-left">
          <thead>
            <tr>
              <th>Hostname</th>
              <th>IP Address</th>
              <th>MAC Address</th>
              <th>User/Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="device in devices" :key="device.mac_address">
              <td>{{ device.hostname || 'Unknown' }}</td>
              <td>{{ device.ip_address }}</td>
              <td class="text-muted">{{ device.mac_address }}</td>
              <td>
                <span class="status-badge" :class="device.is_authenticated ? 'auth' : 'unauth'">
                  {{ device.is_authenticated ? (device.user || 'Authenticated') : 'Unauthenticated' }}
                </span>
              </td>
              <td>
                <button class="btn-small btn-danger" @click="kickDevice(device.mac_address)">Kick</button>
              </td>
            </tr>
            <tr v-if="devices.length === 0">
              <td colspan="5" class="text-center text-muted py-4">No devices connected</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { io } from 'socket.io-client'

const router = useRouter()
const devices = ref([])
let socket = null

const activeUsersCount = computed(() => {
  return devices.value.filter(d => d.is_authenticated).length
})

async function fetchDevices() {
  try {
    const res = await fetch('/api/admin/devices')
    if (res.ok) {
      devices.value = await res.json()
    } else if (res.status === 401 || res.status === 403) {
      router.push('/login')
    }
  } catch (err) {
    console.error("Failed to fetch devices", err)
  }
}

async function kickDevice(mac) {
  if (confirm(`Are you sure you want to kick device ${mac}?`)) {
    // Call kick API
    alert(`Device ${mac} kicked (simulation)`)
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' })
  router.push('/login')
}

onMounted(() => {
  fetchDevices()
  
  // Setup WebSocket connection for live updates
  socket = io()
  socket.on('devices_update', (data) => {
    devices.value = data
  })
})

onUnmounted(() => {
  if (socket) socket.disconnect()
})
</script>

<style scoped>
.table-responsive {
  overflow-x: auto;
}
table {
  border-collapse: collapse;
}
th, td {
  padding: 1rem;
  border-bottom: 1px solid var(--border-color);
}
th {
  color: var(--text-muted);
  font-weight: 500;
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.text-2xl {
  font-size: 2rem;
  font-weight: 600;
  font-family: var(--font-display);
}
.flex-1 {
  flex: 1;
}
.py-4 {
  padding-top: 1rem;
  padding-bottom: 1rem;
}
.btn-small {
  padding: 0.25rem 0.75rem;
  font-size: 0.875rem;
  border-radius: 4px;
}
.status-badge {
  display: inline-block;
  padding: 0.25rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
}
.status-badge.auth {
  background-color: rgba(16, 185, 129, 0.1);
  color: #10b981;
}
.status-badge.unauth {
  background-color: rgba(161, 161, 170, 0.1);
  color: #a1a1aa;
}
</style>
