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

# 4. Detect Wi-Fi interface and copy config templates
WIFI_IFACE=$(ls /sys/class/net | grep -E '^wl|^wlan' | head -n 1)
if [ -z "$WIFI_IFACE" ]; then
    echo "Warning: Could not detect Wi-Fi interface. Falling back to wlan0."
    WIFI_IFACE="wlan0"
else
    echo "Detected Wi-Fi interface: $WIFI_IFACE"
fi

sed "s|interface=wlan0|interface=$WIFI_IFACE|g" config_templates/dnsmasq.conf | sudo tee /etc/dnsmasq.conf > /dev/null
sed "s|interface=wlan0|interface=$WIFI_IFACE|g" config_templates/hostapd.conf | sudo tee /etc/hostapd/hostapd.conf > /dev/null
sed -i "s|WIFI_IFACE = \"wlan0\"|WIFI_IFACE = \"$WIFI_IFACE\"|g" backend/network.py

# Assign the static IP to the interface immediately
sudo ip link set $WIFI_IFACE up
sudo ip addr flush dev $WIFI_IFACE
sudo ip addr add 10.0.0.1/24 dev $WIFI_IFACE || true

# 1. Tell NetworkManager to ignore the Wi-Fi interface so it doesn't wipe our IP
sudo mkdir -p /etc/NetworkManager/conf.d
echo -e "[keyfile]\nunmanaged-devices=interface-name:$WIFI_IFACE" | sudo tee /etc/NetworkManager/conf.d/99-unmanaged-wlan.conf > /dev/null
sudo systemctl restart NetworkManager || true

# 2. Add an automatic network-restore service for boot-ups
sudo tee /etc/systemd/system/restore-wifi-ip.service > /dev/null << EOF
[Unit]
Description=Set Static IP for Captive Portal
Before=dnsmasq.service hostapd.service
After=network.target

[Service]
Type=oneshot
ExecStart=/bin/sleep 3
ExecStart=/usr/bin/ip link set $WIFI_IFACE up
ExecStart=/usr/bin/ip addr flush dev $WIFI_IFACE
ExecStart=/usr/bin/ip addr add 10.0.0.1/24 dev $WIFI_IFACE

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable restore-wifi-ip.service
sudo systemctl start restore-wifi-ip.service
sudo systemctl enable hostapd dnsmasq
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
