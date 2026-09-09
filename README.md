# Nigel Server Captive Portal

Nigel Server is a self-hosted, fully offline captive portal system for a home WiFi hotspot running on Ubuntu Server.
It leverages hostapd, dnsmasq, iptables, and ipset to manage traffic and provide a modern captive portal.

## Setup Instructions

1. **Prerequisites**
   This system is designed for an Ubuntu Server. Ensure you have root privileges.

2. **Run Setup Script**
   Make the script executable and run it:
   ```bash
   chmod +x setup.sh
   ./setup.sh
   ```

3. **Configure Network Services**
   - Review `/etc/dnsmasq.conf` against `config_templates/dnsmasq.conf`
   - Review `/etc/hostapd/hostapd.conf` against `config_templates/hostapd.conf`
   - Restart services: `sudo systemctl restart dnsmasq hostapd`

4. **Configure Sudoers for iptables/ipset**
   The backend needs to run `sudo iptables` and `sudo ipset` without a password. 
   Add a file `/etc/sudoers.d/nigel` with the following content:
   ```text
   root ALL=(ALL) NOPASSWD: /sbin/iptables, /sbin/ipset, /bin/systemctl restart dnsmasq
   ```

5. **Start the Backend**
   Install the `systemd` service:
   ```bash
   sudo cp config_templates/nigel-server.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable nigel-server
   sudo systemctl start nigel-server
   ```

6. **Notifications Configuration**
   Set the following environment variables in your systemd unit or `.env` file to enable notifications:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
   - `DISCORD_WEBHOOK_URL`

## Architecture

- **Backend:** Python Flask + SQLite + Flask-SocketIO
- **Frontend:** Vue 3 + Vite + Vanilla CSS
- **Routing:** Unauthenticated traffic is redirected to the Flask backend via iptables NAT rules. Authenticated MAC addresses are added to an `ipset` to bypass the captive portal redirection.
