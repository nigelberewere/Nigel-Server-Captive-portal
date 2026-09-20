<template>
  <div class="container about-page">
    <header class="flex justify-between items-center mb-8">
      <h1 class="brand-logo">{{ portalName }}</h1>
      <router-link to="/hub" class="btn btn-secondary">Back</router-link>
    </header>
    <section class="card">
      <h2>About Nigel Server</h2>
      <p class="text-muted mt-4">Nigel Server provides offline access to the services hosted on this network.</p>
      <h3 class="mt-8">Network rules</h3>
      <ul class="rules-list mt-4">
        <li>Use this network only with permission from the server owner.</li>
        <li>Unauthenticated devices can reach the sign-in portal, DNS, and DHCP only.</li>
        <li>Do not share account credentials or voucher codes.</li>
        <li>Access may end when a time window, quota, voucher, or guest lease expires.</li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { loadPortalConfig, portalName } from '../config'

onMounted(loadPortalConfig)
</script>

<style scoped>
.rules-list {
  padding-left: 1.25rem;
  color: var(--text-muted);
}
.rules-list li + li {
  margin-top: 0.75rem;
}
</style>
