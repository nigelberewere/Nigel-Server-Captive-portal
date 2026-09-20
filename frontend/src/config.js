import { ref } from 'vue'

export const portalName = ref('Captive Portal')

export async function loadPortalConfig() {
  try {
    const response = await fetch('/api/config')
    if (response.ok) {
      const config = await response.json()
      if (config.portal_name) portalName.value = config.portal_name
    }
  } catch (error) {
    // Keep the generic local fallback when the API is unavailable.
  }
}