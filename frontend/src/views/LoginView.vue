<template>
  <div class="login-container">
    <div class="card login-card">
      <div class="text-center mb-8">
        <h1 class="brand-logo">Nigel<span>Server</span></h1>
        <p class="text-muted mt-2">Sign in to access the network</p>
      </div>

      <form @submit.prevent="handleLogin" v-if="mode === 'login'">
        <div class="input-group">
          <label>Username</label>
          <input type="text" v-model="loginData.username" required placeholder="Enter your username" />
        </div>
        <div class="input-group">
          <label>Password</label>
          <input type="password" v-model="loginData.password" required placeholder="Enter your password" />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="btn w-full mt-4" :disabled="loading">
          {{ loading ? 'Connecting...' : 'Connect' }}
        </button>
        
        <div class="mt-6 text-center text-sm text-muted">
          <p>Don't have an account?</p>
          <div class="flex justify-center gap-4 mt-2">
            <a href="#" @click.prevent="mode = 'voucher'">Use a Voucher</a>
            <span class="text-muted">•</span>
            <a href="#" @click.prevent="mode = 'request'">Request Access</a>
          </div>
        </div>
      </form>

      <form @submit.prevent="handleVoucher" v-if="mode === 'voucher'">
        <div class="input-group">
          <label>Voucher Code</label>
          <input type="text" v-model="voucherCode" required placeholder="Enter 8-digit code" />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <button type="submit" class="btn w-full mt-4" :disabled="loading">
          {{ loading ? 'Verifying...' : 'Apply Voucher' }}
        </button>
        <div class="mt-4 text-center text-sm">
          <a href="#" @click.prevent="mode = 'login'">Back to Login</a>
        </div>
      </form>
      
      <form @submit.prevent="handleRequest" v-if="mode === 'request'">
        <div class="input-group">
          <label>Your Name</label>
          <input type="text" v-model="requestData.name" required placeholder="How should we call you?" />
        </div>
        <div class="input-group">
          <label>Reason / Note (Optional)</label>
          <input type="text" v-model="requestData.note" placeholder="E.g. visiting for the weekend" />
        </div>
        <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-msg">{{ successMsg }}</div>
        <button type="submit" class="btn w-full mt-4" :disabled="loading || successMsg">
          {{ loading ? 'Sending...' : 'Request Access' }}
        </button>
        <div class="mt-4 text-center text-sm">
          <a href="#" @click.prevent="mode = 'login'">Back to Login</a>
        </div>
      </form>

    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const mode = ref('login') // login, voucher, request
const loading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const loginData = ref({ username: '', password: '' })
const voucherCode = ref('')
const requestData = ref({ name: '', note: '' })

// In a real captive portal scenario, the OS usually appends a MAC or IP in the redirect URL
// For this demo, we'll try to extract it from query params or let backend handle it by IP
const urlParams = new URLSearchParams(window.location.search);
const mac_address = urlParams.get('mac') || '';

async function handleLogin() {
  loading.value = true
  errorMsg.value = ''
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
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await fetch('/api/auth/voucher', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code: voucherCode.value, mac_address })
    })
    const data = await res.json()
    if (res.ok) {
      router.push('/hub')
    } else {
      errorMsg.value = data.message || 'Invalid voucher'
    }
  } catch (err) {
    errorMsg.value = 'Network error'
  } finally {
    loading.value = false
  }
}

async function handleRequest() {
  loading.value = true
  errorMsg.value = ''
  // Mock request flow
  setTimeout(() => {
    successMsg.value = 'Access requested. Please wait for the admin to approve your device.'
    loading.value = false
  }, 1000)
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
