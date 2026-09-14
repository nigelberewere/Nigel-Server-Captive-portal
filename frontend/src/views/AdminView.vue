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
      <div class="card flex-1">
        <h3 class="text-muted">Pending Approvals</h3>
        <p class="text-2xl mt-2" style="color: var(--primary-color)">{{ pendingUsersCount }}</p>
      </div>
    </div>

    <!-- Tabs -->
    <div class="tabs mb-4">
      <button :class="{ active: currentTab === 'devices' }" @click="currentTab = 'devices'">Live Devices</button>
      <button :class="{ active: currentTab === 'users' }" @click="currentTab = 'users'">User Accounts</button>
      <button :class="{ active: currentTab === 'vouchers' }" @click="currentTab = 'vouchers'">Vouchers</button>
    </div>

    <!-- Devices Tab -->
    <div class="card" v-if="currentTab === 'devices'">
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

    <!-- Users Tab -->
    <div class="card" v-if="currentTab === 'users'">
      <div class="flex justify-between items-center mb-4">
        <h2>User Management</h2>
        <button class="btn" @click="showAddUser = true">Add User</button>
      </div>

      <div class="table-responsive">
        <table class="w-full text-left">
          <thead>
            <tr>
              <th>Username</th>
              <th>Role</th>
              <th>Created</th>
              <th>Status</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id">
              <td>{{ user.username }}</td>
              <td style="text-transform: capitalize;">{{ user.role }}</td>
              <td class="text-muted">{{ new Date(user.created_at).toLocaleDateString() }}</td>
              <td>
                <span class="status-badge" :class="user.is_approved ? 'auth' : 'unauth'">
                  {{ user.is_approved ? 'Approved' : 'Pending' }}
                </span>
              </td>
              <td>
                <div class="flex gap-2">
                  <button v-if="!user.is_approved" class="btn-small btn-approve" @click="approveUser(user.id)">Approve</button>
                  <button v-if="user.role !== 'admin'" class="btn-small btn-danger" @click="deleteUser(user.id)">Delete</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Add User Modal (Inline) -->
      <div v-if="showAddUser" class="mt-4 p-4" style="background: var(--surface-light); border-radius: 8px;">
        <h3 class="mb-4">Create New User</h3>
        <div class="flex gap-4 items-end">
          <div class="input-group" style="margin-bottom: 0">
            <label>Username</label>
            <input type="text" v-model="newUser.username" placeholder="Username" />
          </div>
          <div class="input-group" style="margin-bottom: 0">
            <label>Password</label>
            <input type="password" v-model="newUser.password" placeholder="Password" />
          </div>
          <div class="input-group" style="margin-bottom: 0">
            <label>Role</label>
            <select v-model="newUser.role" style="padding: 0.75rem; border-radius: 4px; border: 1px solid var(--border-color); background: var(--surface-color); color: var(--text-color);">
              <option value="user">User</option>
              <option value="admin">Admin</option>
            </select>
          </div>
          <button class="btn" @click="createUser">Create</button>
          <button class="btn btn-secondary" @click="showAddUser = false">Cancel</button>
        </div>
      </div>
    </div>

    <!-- Vouchers Tab -->
    <div class="card" v-if="currentTab === 'vouchers'">
      <div class="flex justify-between items-center mb-4">
        <h2>Voucher Codes</h2>
        <div class="flex gap-2 items-center">
          <input type="number" v-model.number="voucherCount" min="1" max="50" style="width: 80px; padding: 0.5rem" placeholder="Count" />
          <select v-model.number="voucherDuration" style="padding: 0.5rem">
            <option :value="1">1 Hour</option>
            <option :value="24">24 Hours</option>
            <option :value="168">7 Days</option>
          </select>
          <button class="btn" @click="generateVouchers">Generate</button>
        </div>
      </div>

      <div class="table-responsive">
        <table class="w-full text-left" style="font-family: monospace;">
          <thead>
            <tr>
              <th>Code</th>
              <th>Status</th>
              <th>Created</th>
              <th>Expires</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="v in vouchers" :key="v.id">
              <td style="font-size: 1.2rem; font-weight: bold; color: var(--primary-color)">{{ v.code }}</td>
              <td>
                <span class="status-badge" :class="v.used_by_device ? 'unauth' : 'auth'">
                  {{ v.used_by_device ? `Used (${v.used_by_device})` : 'Unused' }}
                </span>
              </td>
              <td class="text-muted" style="font-family: sans-serif">{{ new Date(v.created_at).toLocaleString() }}</td>
              <td class="text-muted" style="font-family: sans-serif">
                {{ v.expires_at ? new Date(v.expires_at).toLocaleString() : (v.duration_hours ? `${v.duration_hours}h after use` : 'No expiry') }}
              </td>
              <td>
                <button class="btn-small btn-danger" @click="deleteVoucher(v.id)">Revoke</button>
              </td>
            </tr>
            <tr v-if="vouchers.length === 0">
              <td colspan="5" class="text-center text-muted py-4">No vouchers created</td>
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
const currentTab = ref('devices')

// Device State
const devices = ref([])
let socket = null

const activeUsersCount = computed(() => devices.value.filter(d => d.is_authenticated).length)
const pendingUsersCount = computed(() => users.value.filter(u => !u.is_approved).length)

// User State
const users = ref([])
const showAddUser = ref(false)
const newUser = ref({ username: '', password: '', role: 'user' })

// Voucher State
const vouchers = ref([])
const voucherCount = ref(1)
const voucherDuration = ref(24)

// --- FETCHING ---
async function fetchDevices() {
  try {
    const res = await fetch('/api/admin/devices')
    if (res.ok) devices.value = await res.json()
    else if (res.status === 401 || res.status === 403) router.push('/login')
  } catch (err) { console.error(err) }
}

async function fetchUsers() {
  try {
    const res = await fetch('/api/admin/users')
    if (res.ok) users.value = await res.json()
  } catch (err) { console.error(err) }
}

async function fetchVouchers() {
  try {
    const res = await fetch('/api/admin/vouchers')
    if (res.ok) vouchers.value = await res.json()
  } catch (err) { console.error(err) }
}

// --- ACTIONS ---
async function kickDevice(mac) {
  if (confirm(`Are you sure you want to kick device ${mac}?`)) {
    try {
      const res = await fetch(`/api/admin/devices/${encodeURIComponent(mac)}/kick`, { method: 'POST' })
      if (res.ok) {
        await fetchDevices()
      } else {
        const data = await res.json().catch(() => ({}))
        alert(data.message || 'Failed to kick device')
      }
    } catch (err) {
      alert('Network error when kicking device')
    }
  }
}

async function approveUser(id) {
  const res = await fetch(`/api/admin/users/${id}/approve`, { method: 'POST' })
  if (res.ok) {
    await fetchUsers()
  } else {
    alert('Failed to approve user')
  }
}

async function createUser() {
  const res = await fetch('/api/admin/users', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(newUser.value)
  })
  if (res.ok) {
    newUser.value = { username: '', password: '', role: 'user' }
    showAddUser.value = false
    await fetchUsers()
  } else {
    const data = await res.json().catch(() => ({}))
    alert(data.message || 'Failed to create user')
  }
}

async function deleteUser(id) {
  if (confirm('Are you sure you want to delete this user?')) {
    try {
      const res = await fetch(`/api/admin/users/${id}`, { method: 'DELETE' })
      if (res.ok) {
        await fetchUsers()
      } else {
        const data = await res.json().catch(() => ({}))
        alert(data.message || 'Failed to delete user')
      }
    } catch (err) {
      alert('Network error when deleting user')
    }
  }
}

async function generateVouchers() {
  const res = await fetch('/api/admin/vouchers', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ count: voucherCount.value, duration_hours: voucherDuration.value })
  })
  if (res.ok) {
    await fetchVouchers()
  } else {
    alert('Failed to generate vouchers')
  }
}

async function deleteVoucher(id) {
  if (confirm('Are you sure you want to revoke this voucher?')) {
    try {
      const res = await fetch(`/api/admin/vouchers/${id}`, { method: 'DELETE' })
      if (res.ok) {
        await fetchVouchers()
      } else {
        const data = await res.json().catch(() => ({}))
        alert(data.message || 'Failed to revoke voucher')
      }
    } catch (err) {
      alert('Network error when revoking voucher')
    }
  }
}

async function logout() {
  await fetch('/api/auth/logout', { method: 'POST' })
  router.push('/login')
}

let pollTimer = null

onMounted(() => {
  fetchDevices()
  fetchUsers()
  fetchVouchers()
  
  try {
    socket = io()
    socket.on('devices_update', () => fetchDevices())
    socket.on('users_update', () => fetchUsers())
    socket.on('vouchers_update', () => fetchVouchers())
  } catch (e) {
    console.error('Socket error:', e)
  }

  // Automatic background refresh every 3 seconds for instant updates without page reload
  pollTimer = setInterval(() => {
    fetchUsers()
    fetchDevices()
    fetchVouchers()
  }, 3000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (socket) socket.disconnect()
})
</script>

<style scoped>
.tabs {
  display: flex;
  gap: 1rem;
  border-bottom: 1px solid var(--border-color);
  padding-bottom: 0.5rem;
}
.tabs button {
  background: none;
  border: none;
  color: var(--text-muted);
  font-weight: 500;
  font-size: 1rem;
  padding: 0.5rem 1rem;
  cursor: pointer;
  border-radius: 4px;
}
.tabs button:hover {
  background: var(--surface-light);
}
.tabs button.active {
  color: var(--accent-color);
  background: rgba(245, 158, 11, 0.15);
}

.table-responsive { overflow-x: auto; }
table { border-collapse: collapse; }
th, td { padding: 1rem; border-bottom: 1px solid var(--border-color); }
th { color: var(--text-muted); font-weight: 500; font-size: 0.875rem; text-transform: uppercase; letter-spacing: 0.05em; }
.text-2xl { font-size: 2rem; font-weight: 600; font-family: var(--font-display); }
.flex-1 { flex: 1; }
.py-4 { padding-top: 1rem; padding-bottom: 1rem; }
.btn-small { padding: 0.35rem 0.85rem; font-size: 0.875rem; border-radius: 6px; }
.btn-approve {
  background-color: #10b981;
  color: #000000;
  border: none;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.2s;
}
.btn-approve:hover {
  background-color: #059669;
}
.status-badge { display: inline-block; padding: 0.25rem 0.5rem; border-radius: 9999px; font-size: 0.75rem; font-weight: 600; }
.status-badge.auth { background-color: rgba(16, 185, 129, 0.15); color: #10b981; }
.status-badge.unauth { background-color: rgba(161, 161, 170, 0.15); color: #a1a1aa; }
.status-badge.used { background-color: rgba(245, 158, 11, 0.15); color: #f59e0b; }
</style>
