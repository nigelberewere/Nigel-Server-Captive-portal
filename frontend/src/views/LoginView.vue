<template>
  <div class="login-container">
    <div class="card login-card">
      <div class="text-center mb-8">
        <h1 class="brand-logo">Nigel<span>Server</span></h1>
        <p class="text-muted mt-2">Sign in to access the network</p>
      </div>

      <!-- Login Form -->
      <form @submit.prevent="handleLogin" v-if="mode === 'login'">
        <div class="input-group">
          <label>Username</label>
          <input type="text" v-model.trim="loginData.username" placeholder="Enter your username" @input="clearMessages" required />
        </div>
        <div class="input-group">
          <label>Password</label>
          <input type="password" v-model="loginData.password" placeholder="Enter your password" @input="clearMessages" required />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="btn w-full mt-4" :disabled="loading">
          {{ loading ? 'Connecting...' : 'Connect' }}
        </button>
        
        <div class="mt-6 text-center text-sm text-muted">
          <p>Don't have an account?</p>
          <div class="flex justify-center gap-4 mt-2">
            <a href="#" @click.prevent="setMode('voucher')">Use a Voucher</a>
            <span class="text-muted">•</span>
            <a href="#" @click.prevent="setMode('request')">Request Access</a>
          </div>
        </div>
      </form>

      <!-- Voucher Form -->
      <form @submit.prevent="handleVoucher" v-if="mode === 'voucher'">
        <div class="input-group">
          <label>Voucher Code</label>
          <input 
            type="text" 
            v-model.trim="voucherCode" 
            placeholder="Enter 8-digit code" 
            @input="voucherCode = voucherCode.toUpperCase(); clearMessages()" 
            style="text-transform: uppercase; font-weight: bold; letter-spacing: 0.1em;"
            required 
          />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="btn w-full mt-4" :disabled="loading">
          {{ loading ? 'Verifying...' : 'Apply Voucher' }}
        </button>
        <div class="mt-4 text-center text-sm">
          <a href="#" @click.prevent="setMode('login')">Back to Login</a>
        </div>
      </form>
      
      <!-- Request Access Form -->
      <form @submit.prevent="handleRequest" v-if="mode === 'request'">
        <div class="input-group">
          <label>Desired Username</label>
          <input type="text" v-model.trim="requestData.username" placeholder="Choose a username" @input="clearMessages" required />
        </div>
        <div class="input-group">
          <label>Password</label>
          <input type="password" v-model="requestData.password" placeholder="Choose a password" @input="clearMessages" required />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-msg">{{ successMsg }}</div>
        <button type="submit" class="btn w-full mt-4" :disabled="loading">
          {{ loading ? 'Sending...' : 'Request Account' }}
        </button>
        <div class="mt-4 text-center text-sm">
          <a href="#" @click.prevent="setMode('login')">Back to Login</a>
        </div>
      </form>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const mode = ref('login') // login, voucher, request
const loading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const loginData = ref({ username: '', password: '' })
const voucherCode = ref('')
const requestData = ref({ username: '', password: '' })

const urlParams = new URLSearchParams(window.location.search);
const mac_address = urlParams.get('mac') || '';

function setMode(newMode) {
  mode.value = newMode
  clearMessages()
}

function clearMessages() {
  errorMsg.value = ''
  successMsg.value = ''
}

// Check if this device is already authenticated
onMounted(async () => {
  try {
    const res = await fetch('/api/auth/status')
    if (res.ok) {
      const data = await res.json()
      if (data.authenticated) {
        if (data.role === 'admin') router.push('/admin')
        else router.push('/hub')
      }
    }
  } catch (err) {
    // offline or backend restarting
  }
})

async function handleLogin() {
  clearMessages()
  if (!loginData.value.username || !loginData.value.password) {
    errorMsg.value = 'Please enter both username and password.'
    return
  }
  loading.value = true
  try {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...loginData.value, mac_address })
    })
    const data = await res.json()
    if (res.ok) {
      if (data.role === 'admin') router.push('/admin')
      else router.push('/hub')
    } else {
      errorMsg.value = data.message || 'Login failed'
    }
  } catch (err) {
    errorMsg.value = 'Network error. Could not reach server.'
  } finally {
    loading.value = false
  }
}

async function handleVoucher() {
  clearMessages()
  const code = voucherCode.value.trim().toUpperCase()
  if (!code) {
    errorMsg.value = 'Please enter a voucher code.'
    return
  }
  loading.value = true
  try {
    const res = await fetch('/api/auth/voucher', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, mac_address })
    })
    const data = await res.json()
    if (res.ok) {
      router.push('/hub')
    } else {
      errorMsg.value = data.message || 'Invalid voucher'
    }
  } catch (err) {
    errorMsg.value = 'Network error. Could not reach server.'
  } finally {
    loading.value = false
  }
}

async function handleRequest() {
  clearMessages()
  if (!requestData.value.username || !requestData.value.password) {
    errorMsg.value = 'Please choose a username and password.'
    return
  }
  loading.value = true
  try {
    const res = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestData.value)
    })
    const data = await res.json()
    if (res.ok) {
      successMsg.value = data.message || 'Account requested! Please wait for the admin to approve it.'
      requestData.value = { username: '', password: '' }
    } else {
      errorMsg.value = data.message || 'Registration failed'
    }
  } catch (err) {
    errorMsg.value = 'Network error. Could not reach server.'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 1rem;
}
.login-card {
  width: 100%;
  max-width: 400px;
}
.w-full {
  width: 100%;
}
.mb-8 {
  margin-bottom: 2rem;
}
.mt-2 {
  margin-top: 0.5rem;
}
.mt-6 {
  margin-top: 1.5rem;
}
.text-sm {
  font-size: 0.875rem;
}
.error-msg {
  color: var(--danger-color);
  font-size: 0.875rem;
  margin-top: 0.5rem;
  text-align: center;
}
.success-msg {
  color: #10b981; /* green */
  font-size: 0.875rem;
  margin-top: 0.5rem;
  text-align: center;
}
</style>
