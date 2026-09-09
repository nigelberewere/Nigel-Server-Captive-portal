#!/bin/bash
set -e

echo "Setting up Nigel Server..."

# 1. Update and install system dependencies
sudo apt-update
sudo apt-get install -y python3 python3-venv python3-pip iptables ipset dnsmasq hostapd nodejs npm

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
# sudo cp config_templates/dnsmasq.conf /etc/dnsmasq.conf
# sudo cp config_templates/hostapd.conf /etc/hostapd/hostapd.conf

# 5. Setup Systemd Service
# sudo cp config_templates/nigel-server.service /etc/systemd/system/
# sudo systemctl daemon-reload
# sudo systemctl enable nigel-server
# sudo systemctl start nigel-server

echo "Setup complete. Please verify /etc/dnsmasq.conf and /etc/hostapd/hostapd.conf."
