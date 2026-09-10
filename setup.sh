#!/bin/bash
set -e

echo "Setting up Nigel Server..."

# 1. Update and install system dependencies
sudo apt update
sudo apt install -y python3 python3-venv python3-pip iptables ipset dnsmasq hostapd nodejs npm

# 2. Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt

# 3. Setup Frontend
cd frontend
npm install
npm run build
cd ..

# 4. Copy config templates to /etc
sudo cp config_templates/dnsmasq.conf /etc/dnsmasq.conf
sudo cp config_templates/hostapd.conf /etc/hostapd/hostapd.conf
sudo systemctl restart dnsmasq hostapd

# 4.5. Configure Sudoers for iptables/ipset
echo "root ALL=(ALL) NOPASSWD: /sbin/iptables, /sbin/ipset, /bin/systemctl restart dnsmasq" | sudo tee /etc/sudoers.d/nigel
sudo chmod 0440 /etc/sudoers.d/nigel

# 5. Setup Systemd Service dynamically with the current path
sed "s|/opt/nigel-server|$PWD|g" config_templates/nigel-server.service | sudo tee /etc/systemd/system/nigel-server.service > /dev/null
sudo systemctl daemon-reload
sudo systemctl enable nigel-server
sudo systemctl start nigel-server

echo "Setup complete. Please verify /etc/dnsmasq.conf and /etc/hostapd/hostapd.conf."
