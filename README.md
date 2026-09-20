# Nigel Server Captive Portal

Nigel Server is a self-hosted, fully offline captive portal system for a home WiFi hotspot running on Ubuntu Server.
It leverages hostapd, dnsmasq, iptables, and ipset to manage traffic and provide a modern captive portal.

## Setup Instructions

1. **Prerequisites**
   This system is designed for an Ubuntu Server. Ensure you have root privileges.

2. **Install software**
   Make the script executable and run it:
   ```bash
   chmod +x setup.sh
   sudo ./setup.sh install
   ```
   This phase requires internet and does not switch or reconfigure the Wi-Fi interface. Set `SKIP_FRONTEND_BUILD=1` when deploying a prebuilt `frontend/dist` directory from a connected build machine.

   To build the offline frontend elsewhere, copy the repository to a machine with Node.js 18 or newer, run `cd frontend && npm install && npm run build`, then copy `frontend/dist` to the server before running `SKIP_FRONTEND_BUILD=1 sudo ./setup.sh install`.

3. **Enable the hotspot**
   ```bash
   sudo WIFI_IFACE=wlo1 ./setup.sh enable-hotspot
   ```
   The interface is detected once and stored in `/etc/nigel/nigel.env`. The command writes dedicated hostapd/dnsmasq configuration, ignores old `/etc/dnsmasq.d` fragments such as `ubuntu-fan`, and switches the Wi-Fi card to AP mode.

   Use `sudo nigel-hotspot status` to inspect the interface, AP+STA capability, and services. Use `sudo nigel-hotspot off` from the local console before updating the server; it removes the hotspot address, restores managed/client mode, and re-enables the existing client-network configuration. Use `sudo nigel-hotspot on` to return to AP mode.

   If `iw list` does not advertise AP+STA concurrency, the card must be switched between client and hotspot modes with `nigel-hotspot on|off`.

4. **Firewall cleanup**
   The service runs as root because it owns iptables/ipset and port 5000; no broad sudoers entry is installed. Use `sudo ./venv/bin/python backend/app.py --cleanup` to remove Nigel chains and the MAC ipset.

5. **Network cleanup**
   To remove previous hotspot configuration after making a backup, run `sudo ./scripts/clean-network.sh`. Use `--dry-run` first. The script searches for and removes legacy `192.168.4.1` address writers without printing Wi-Fi credentials, leaves Ethernet/client credentials intact, and only removes Nigel-owned firewall chains and ipsets.

6. **Notifications Configuration**
   Set the following environment variables in your systemd unit or `.env` file to enable notifications:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `DISCORD_WEBHOOK_URL`

## Architecture

- **Backend:** Python Flask + SQLite + Flask-SocketIO
- **Frontend:** Vue 3 + Vite + Vanilla CSS
- **Routing:** Unauthenticated traffic is redirected to the Flask backend via iptables NAT rules. Authenticated MAC addresses are added to an `ipset` to bypass the captive portal redirection.
