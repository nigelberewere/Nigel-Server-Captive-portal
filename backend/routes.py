from flask import Blueprint, request, jsonify, send_file
import logging
import os
from flask_login import login_user, logout_user, login_required, current_user
from models import AuditLog, User, Device, Voucher, Setting, RegisteredService, PasswordResetToken, TrustedDevice
from extensions import db, socketio
import network
import datetime
import secrets
import string
import threading
import time
import re
import io
import qrcode
import hashlib
from pathlib import Path
from zoneinfo import ZoneInfo
from notify import notify_all_async

_rate_limit = {}
_rate_lock = threading.Lock()
MAC_RE = re.compile(r'^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$', re.IGNORECASE)


def configured_now():
    timezone_name = os.environ.get('NIGEL_TIMEZONE', 'system')
    timezone = datetime.datetime.now().astimezone().tzinfo if timezone_name == 'system' else ZoneInfo(timezone_name)
    return datetime.datetime.now(timezone)


def _client_mac():
    return network.get_mac_from_ip(request.remote_addr)


def _throttled(action, limit, window=60):
    key = (action, request.remote_addr or 'unknown')
    now = time.monotonic()
    with _rate_lock:
        attempts = [stamp for stamp in _rate_limit.get(key, []) if now - stamp < window]
        if len(attempts) >= limit:
            _rate_limit[key] = attempts
            return True
        attempts.append(now)
        _rate_limit[key] = attempts
    return False


def _device_for_mac(mac_address):
    return Device.query.filter_by(mac_address=mac_address).first()


def _admin_mac(mac_address):
    if not isinstance(mac_address, str) or not MAC_RE.fullmatch(mac_address):
        return None
    return mac_address.lower()


def _setting_bool(key, default=True):
    setting = db.session.get(Setting, key)
    return default if setting is None else setting.value.lower() in {'1', 'true', 'yes', 'on'}


def _setting_int(key, default):
    setting = db.session.get(Setting, key)
    try:
        return int(setting.value) if setting else default
    except ValueError:
        return default


def _audit(action, details='', user_id=None):
    db.session.add(AuditLog(action=action, details=details, user_id=user_id))


def _notify_device(action, mac_address, username=None):
    subject = f'Device {action}: {mac_address}'
    if username:
        subject += f' ({username})'
    notify_all_async(subject)

api_bp = Blueprint('api', __name__)


@api_bp.route('/config', methods=['GET'])
def portal_config():
    setting = db.session.get(Setting, 'portal_name')
    return jsonify({'portal_name': setting.value if setting else os.environ.get('PORTAL_NAME', 'Captive Portal')}), 200

def notify_users_changed():
    try:
        socketio.emit('users_update')
    except Exception:
        pass

def notify_devices_changed():
    try:
        socketio.emit('devices_update')
    except Exception:
        pass

def notify_vouchers_changed():
    try:
        socketio.emit('vouchers_update')
    except Exception:
        pass

@api_bp.route('/auth/status', methods=['GET'])
def auth_status():
    client_ip = request.remote_addr
    mac_address = _client_mac()
    
    is_auth = False
    role = 'guest'
    username = None
    
    trusted = TrustedDevice.query.filter_by(mac_address=mac_address).first() if mac_address else None
    if trusted:
        is_auth = True
        role = 'trusted'
        username = trusted.label or 'Trusted device'
    elif current_user.is_authenticated:
        is_auth = True
        role = current_user.role
        username = current_user.username
    else:
        dev = None
        if mac_address and not mac_address.startswith('ip-'):
            dev = Device.query.filter_by(mac_address=mac_address).first()
        if dev and dev.is_authenticated and not dev.is_blocked:
            is_auth = True
            if dev.user:
                role = dev.user.role
                username = dev.user.username
            else:
                role = 'voucher'
                
    return jsonify({
        'authenticated': is_auth,
        'role': role,
        'username': username,
        'ip': client_ip,
        'mac': mac_address
    }), 200

@api_bp.route('/auth/register', methods=['POST'])
def register():
    if not _setting_bool('registration_enabled', True):
        return jsonify({'message': 'Registration is disabled'}), 403
    if _throttled('register', 5):
        return jsonify({'message': 'Too many registration attempts'}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password')
    client_ip = request.remote_addr
    mac_address = _client_mac()
    
    if not username or not password or not mac_address:
        return jsonify({'message': 'Please provide both username and password'}), 400
        
    if User.query.filter_by(username=username).first():
        return jsonify({'message': 'Username already exists'}), 400
        
    # By default, new registrations are NOT approved until admin approves
    new_user = User(username=username, role='user', is_approved=False)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.flush()

    # Link device to pending user
    device = None
    if mac_address and not mac_address.startswith('ip-'):
        device = Device.query.filter_by(mac_address=mac_address).first()

    if not device:
        device = Device(mac_address=mac_address, ip_address=client_ip, user_id=new_user.id, is_authenticated=False)
        db.session.add(device)
    else:
        device.user_id = new_user.id
        device.is_authenticated = False

    db.session.commit()
    _audit('register', f'username={username}; mac={mac_address}')
    db.session.commit()
    notify_users_changed()
    return jsonify({'message': 'Account requested! Waiting for admin approval.'}), 201

@api_bp.route('/auth/login', methods=['POST'])
def login():
    if _throttled('login', 10):
        return jsonify({'message': 'Too many login attempts'}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password')
    client_ip = request.remote_addr
    mac_address = _client_mac()
    
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        # Admin is always approved, check is_approved for normal users
        if user.role != 'admin' and not user.is_approved:
            return jsonify({'message': 'Account pending admin approval.'}), 403
        if not mac_address:
            return jsonify({'message': 'Could not identify this device'}), 400
        existing_device = Device.query.filter_by(mac_address=mac_address).first()
        if existing_device and existing_device.is_blocked:
            return jsonify({'message': 'This device is blocked'}), 403
        if user.role == 'admin' and user.must_change_password:
            login_user(user)
            return jsonify({'message': 'Password change required', 'must_change_password': True}), 200

        login_user(user)

        # Authenticate the device
        device = None
        if mac_address and not mac_address.startswith('ip-'):
            device = Device.query.filter_by(mac_address=mac_address).first()

        if not device:
            device = Device(mac_address=mac_address, ip_address=client_ip)
            db.session.add(device)
        else:
            device.mac_address = mac_address
            device.ip_address = client_ip
            
        device.user_id = user.id
        device.is_authenticated = True
        device.access_expires_at = None
        device.connected_at = configured_now()
        device.last_seen = configured_now()
        db.session.commit()
        _audit('login', f'mac={mac_address}', user.id)
        db.session.commit()
        _notify_device('authenticated', mac_address, user.username)
        
        # Whitelist device in firewall (both MAC and IP)
        network.add_device_to_ipset(mac_address=mac_address, ip_address=client_ip)
        notify_devices_changed()
            
        return jsonify({'message': 'Logged in successfully', 'role': user.role}), 200
        
    return jsonify({'message': 'Invalid credentials'}), 401

@api_bp.route('/auth/password', methods=['POST'])
@login_required
def change_password():
    data = request.get_json(silent=True) or {}
    password = data.get('password')
    if not isinstance(password, str) or len(password) < 12:
        return jsonify({'message': 'Password must be at least 12 characters'}), 400
    current_user.set_password(password)
    current_user.must_change_password = False
    db.session.commit()
    return jsonify({'message': 'Password changed'}), 200


@api_bp.route('/auth/password-reset', methods=['POST'])
def request_password_reset():
    if _throttled('password-reset', 3):
        return jsonify({'message': 'Too many reset requests'}), 429
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    user = User.query.filter_by(username=username).first()
    response = {'message': 'If that account exists, reset instructions were created'}
    if not user:
        return jsonify(response), 200
    raw_token = secrets.token_urlsafe(32)
    db.session.add(PasswordResetToken(
        user_id=user.id,
        token_hash=hashlib.sha256(raw_token.encode('utf-8')).hexdigest(),
        expires_at=configured_now() + datetime.timedelta(minutes=15)
    ))
    db.session.commit()
    notify_all_async(f'Password reset requested for account {username}')
    return jsonify(response), 200


@api_bp.route('/auth/password-reset/confirm', methods=['POST'])
def confirm_password_reset():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    password = data.get('password')
    if not isinstance(token, str) or not isinstance(password, str) or len(password) < 12:
        return jsonify({'message': 'Token and a 12-character password are required'}), 400
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    reset = PasswordResetToken.query.filter_by(token_hash=token_hash, used_at=None).first()
    if not reset or reset.expires_at <= configured_now():
        return jsonify({'message': 'Invalid or expired reset token'}), 400
    reset.user.set_password(password)
    reset.user.must_change_password = False
    reset.used_at = configured_now()
    db.session.commit()
    return jsonify({'message': 'Password reset'}), 200

@api_bp.route('/auth/logout', methods=['POST'])
def logout():
    mac_address = _client_mac()
    
    if mac_address:
        device = Device.query.filter_by(mac_address=mac_address).first()
        if device:
            device.is_authenticated = False
            _audit('logout', f'mac={mac_address}', device.user_id)
            db.session.commit()
            network.remove_device_from_ipset(mac_address=mac_address, ip_address=device.ip_address)
            _notify_device('disconnected', mac_address)
            notify_devices_changed()
            
    if current_user.is_authenticated:
        logout_user()
    return jsonify({'message': 'Logged out'}), 200

@api_bp.route('/auth/voucher', methods=['POST'])
def use_voucher():
    if not _setting_bool('vouchers_enabled', True):
        return jsonify({'message': 'Vouchers are disabled'}), 403
    if _throttled('voucher', 10):
        return jsonify({'message': 'Too many voucher attempts'}), 429
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip().upper()
    client_ip = request.remote_addr
    mac_address = _client_mac()
    
    if not code or not mac_address:
        return jsonify({'message': 'Please enter a voucher code'}), 400
        
    voucher = Voucher.query.filter_by(code=code).first()
    if not voucher:
        return jsonify({'message': 'Invalid voucher code'}), 400
        
    now = configured_now()
    if voucher.expires_at and voucher.expires_at <= now:
        return jsonify({'message': 'This voucher has expired'}), 400
        
    # Check if voucher was already used by a DIFFERENT device
    if voucher.used_by_device and voucher.used_by_device != mac_address:
        return jsonify({'message': f'Voucher already used by device {voucher.used_by_device}'}), 400
        
    # Set used device identifier
    voucher.used_by_device = mac_address
    
    # If duration_hours was set, start the expiration timer from first use
    if voucher.duration_hours and (not voucher.expires_at or voucher.expires_at > now + datetime.timedelta(hours=voucher.duration_hours)):
        voucher.expires_at = now + datetime.timedelta(hours=voucher.duration_hours)
        
    # Find or register device
    device = None
    if mac_address and not mac_address.startswith('ip-'):
        device = Device.query.filter_by(mac_address=mac_address).first()

    if not device:
        device = Device(mac_address=mac_address, ip_address=client_ip)
        db.session.add(device)
    else:
        device.mac_address = mac_address
        device.ip_address = client_ip
        
    device.is_authenticated = True
    device.access_expires_at = None
    device.connected_at = now
    device.last_seen = now
    db.session.commit()
    _audit('voucher_auth', f'mac={mac_address}; voucher={voucher.code}', device.user_id)
    db.session.commit()
    _notify_device('authenticated by voucher', mac_address)
    
    # Instantly allow device traffic through firewall
    network.add_device_to_ipset(mac_address=mac_address, ip_address=client_ip)
    notify_devices_changed()
    notify_vouchers_changed()
    
    return jsonify({
        'message': 'Voucher applied! Network access granted.',
        'mac_address': mac_address,
        'expires_at': voucher.expires_at.isoformat() if voucher.expires_at else None
    }), 200


@api_bp.route('/auth/guest', methods=['POST'])
def guest_access():
    if not _setting_bool('guest_enabled', False):
        return jsonify({'message': 'Guest access is disabled'}), 403
    if _throttled('guest', 3):
        return jsonify({'message': 'Too many guest requests'}), 429
    mac_address = _client_mac()
    if not mac_address:
        return jsonify({'message': 'Could not identify this device'}), 400
    data = request.get_json(silent=True) or {}
    try:
        duration = max(1, min(_setting_int('guest_max_hours', 24), int(data.get('duration_hours', _setting_int('guest_default_hours', 2)))))
    except (TypeError, ValueError):
        return jsonify({'message': 'Invalid duration'}), 400
    now = configured_now()
    device = Device.query.filter_by(mac_address=mac_address).first()
    if device and device.is_blocked:
        return jsonify({'message': 'This device is blocked'}), 403
    if not device:
        device = Device(mac_address=mac_address, ip_address=request.remote_addr)
        db.session.add(device)
    device.is_authenticated = True
    device.access_expires_at = now + datetime.timedelta(hours=duration)
    device.connected_at = now
    device.last_seen = now
    db.session.flush()
    _audit('guest_access', f'mac={mac_address}; hours={duration}', device.user_id)
    db.session.commit()
    network.add_device_to_ipset(mac_address=mac_address)
    _notify_device('granted guest access', mac_address)
    notify_devices_changed()
    return jsonify({'message': 'Guest access granted', 'expires_at': device.access_expires_at.isoformat()}), 200

import subprocess

def discover_services():
    active_services = []
    try:
        result = subprocess.run(['ss', '-tln'], stdout=subprocess.PIPE, text=True)
        output = result.stdout
        
        all_services = RegisteredService.query.all()
        for svc in all_services:
            if svc.check_port:
                # Check if port is in listening state
                port_str = f":{svc.check_port} "
                if port_str in output:
                    active_services.append({
                        "id": svc.id, "name": svc.name, "description": svc.description,
                        "url": svc.url, "icon": svc.icon
                    })
            else:
                # If no port check required, always show it
                active_services.append({
                    "id": svc.id, "name": svc.name, "description": svc.description,
                    "url": svc.url, "icon": svc.icon
                })
    except Exception:
        pass
        
    return active_services

@api_bp.route('/hub/services', methods=['GET'])
def get_services():
    # Dynamically discover services from active ports
    services = discover_services()
    return jsonify(services), 200

# Admin endpoints for managing services
@api_bp.route('/admin/services', methods=['GET', 'POST'])
@login_required
def admin_manage_services():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    if request.method == 'GET':
        services = RegisteredService.query.all()
        return jsonify([{
            "id": s.id, "name": s.name, "description": s.description,
            "url": s.url, "icon": s.icon, "check_port": s.check_port
        } for s in services]), 200
        
    if request.method == 'POST':
        data = request.get_json()
        new_svc = RegisteredService(
            name=data['name'], description=data.get('description'),
            url=data['url'], icon=data.get('icon', 'link'), check_port=data.get('check_port')
        )
        db.session.add(new_svc)
        db.session.commit()
        return jsonify({"message": "Service added", "id": new_svc.id}), 201

@api_bp.route('/admin/services/<int:svc_id>', methods=['DELETE'])
@login_required
def admin_delete_service(svc_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    svc = RegisteredService.query.get(svc_id)
    if svc:
        db.session.delete(svc)
        db.session.commit()
        return jsonify({"message": "Service deleted"}), 200
    return jsonify({"message": "Not found"}), 404


@api_bp.route('/admin/devices', methods=['GET'])
@login_required
def get_devices():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    devices = Device.query.all()
    res = []
    for d in devices:
        telemetry = network.get_device_telemetry(d.mac_address)
        d.hostname = telemetry['hostname'] or d.hostname
        d.data_used_mb = telemetry['data_used_mb']
        res.append({
            'mac_address': d.mac_address,
            'ip_address': d.ip_address,
            'hostname': d.hostname,
            'is_authenticated': d.is_authenticated,
            'is_blocked': d.is_blocked,
            'data_used_mb': d.data_used_mb,
            'signal_strength': telemetry['signal_strength'],
            'user': d.user.username if d.user else ('Voucher' if d.is_authenticated else 'Unauthenticated')
        })
    return jsonify(res), 200


@api_bp.route('/admin/trusted-devices', methods=['GET', 'POST'])
@login_required
def trusted_devices():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        mac_address = _admin_mac(data.get('mac_address'))
        if not mac_address:
            return jsonify({'message': 'Invalid MAC address'}), 400
        trusted = TrustedDevice.query.filter_by(mac_address=mac_address).first()
        if not trusted:
            trusted = TrustedDevice(mac_address=mac_address, label=(data.get('label') or '').strip() or None)
            db.session.add(trusted)
        else:
            trusted.label = (data.get('label') or '').strip() or trusted.label
        db.session.commit()
        network.add_trusted_device(mac_address)
        _audit('trusted_device_added', f'mac={mac_address}', current_user.id)
        db.session.commit()
        notify_devices_changed()
        return jsonify({'message': 'Trusted device saved'}), 201
    return jsonify([{'id': d.id, 'mac_address': d.mac_address, 'label': d.label} for d in TrustedDevice.query.order_by(TrustedDevice.created_at.desc()).all()]), 200


@api_bp.route('/admin/trusted-devices/<path:mac_address>', methods=['DELETE'])
@login_required
def delete_trusted_device(mac_address):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    mac_address = _admin_mac(mac_address)
    if not mac_address:
        return jsonify({'message': 'Invalid MAC address'}), 400
    trusted = TrustedDevice.query.filter_by(mac_address=mac_address).first()
    if trusted:
        db.session.delete(trusted)
        db.session.commit()
    network.remove_trusted_device(mac_address)
    return jsonify({'message': 'Trusted device removed'}), 200


@api_bp.route('/admin/audit', methods=['GET'])
@login_required
def audit_logs():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    logs = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(500).all()
    return jsonify([{
        'id': log.id, 'timestamp': log.timestamp.isoformat(), 'action': log.action,
        'details': log.details, 'user_id': log.user_id
    } for log in logs]), 200


@api_bp.route('/wifi/qr', methods=['GET'])
@login_required
def wifi_qr():
    ssid = os.environ.get('WIFI_SSID', 'Nigel Server')
    passphrase_file = os.environ.get('WIFI_PASSPHRASE_FILE', '/etc/nigel/wifi-passphrase')
    try:
        passphrase = Path(passphrase_file).read_text(encoding='utf-8').strip()
    except OSError:
        passphrase = ''
    portal_url = os.environ.get('PORTAL_ORIGIN', 'http://localhost:5000')
    security = 'WPA' if passphrase else 'nopass'
    def escape(value):
        return ''.join('\\' + char if char in '\\;,:' + '"' else char for char in value)
    payload = f'WIFI:T:{security};S:{escape(ssid)};P:{escape(passphrase)};;'
    image = qrcode.make(payload)
    output = io.BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return send_file(output, mimetype='image/png', download_name='nigel-wifi.png')


@api_bp.route('/portal/qr', methods=['GET'])
@login_required
def portal_qr():
    image = qrcode.make(os.environ.get('PORTAL_ORIGIN', 'http://localhost:5000'))
    output = io.BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return send_file(output, mimetype='image/png', download_name='nigel-portal.png')

@api_bp.route('/admin/devices/<path:mac_address>/kick', methods=['POST', 'DELETE'])
@login_required
def kick_device(mac_address):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    mac_address = _admin_mac(mac_address)
    if not mac_address:
        return jsonify({'message': 'Invalid MAC address'}), 400
    device = Device.query.filter_by(mac_address=mac_address).first()
    if device:
        device.is_authenticated = False
        _audit('kick', f'mac={mac_address}', device.user_id)
        db.session.commit()
        network.remove_device_from_ipset(mac_address=mac_address, ip_address=device.ip_address)
        _notify_device('kicked', mac_address)
        return jsonify({'message': f'Device {mac_address} kicked successfully'}), 200
        
    # Also remove from ipset directly
    network.remove_device_from_ipset(mac_address=mac_address)
    return jsonify({'message': f'Device {mac_address} removed from firewall'}), 200


@api_bp.route('/admin/devices/<path:mac_address>/block', methods=['POST'])
@login_required
def block_device(mac_address):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    mac_address = _admin_mac(mac_address)
    if not mac_address:
        return jsonify({'message': 'Invalid MAC address'}), 400
    device = Device.query.filter_by(mac_address=mac_address).first()
    if not device:
        return jsonify({'message': 'Device not found'}), 404
    device.is_blocked = True
    device.is_authenticated = False
    _audit('block', f'mac={mac_address}', device.user_id)
    db.session.commit()
    network.remove_device_from_ipset(mac_address=device.mac_address)
    _notify_device('blocked', mac_address)
    notify_devices_changed()
    return jsonify({'message': 'Device blocked'}), 200


@api_bp.route('/admin/devices/<path:mac_address>/unblock', methods=['POST'])
@login_required
def unblock_device(mac_address):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    mac_address = _admin_mac(mac_address)
    if not mac_address:
        return jsonify({'message': 'Invalid MAC address'}), 400
    device = Device.query.filter_by(mac_address=mac_address).first()
    if not device:
        return jsonify({'message': 'Device not found'}), 404
    device.is_blocked = False
    _audit('unblock', f'mac={mac_address}', device.user_id)
    db.session.commit()
    notify_devices_changed()
    return jsonify({'message': 'Device unblocked'}), 200

# User Management Endpoints
@api_bp.route('/admin/users', methods=['GET', 'POST'])
@login_required
def admin_users():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    if request.method == 'GET':
        users = User.query.all()
        return jsonify([{
            'id': u.id, 'username': u.username, 'role': u.role, 
            'is_approved': u.is_approved, 'created_at': u.created_at.isoformat(),
            'quota_mb': u.quota_mb, 'time_window_start': u.time_window_start,
            'time_window_end': u.time_window_end
        } for u in users]), 200
        
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        username = (data.get('username') or '').strip()
        password = data.get('password')
        if not username or not password:
            return jsonify({'message': 'Username and password required'}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({'message': 'Username exists'}), 400
            
        u = User(username=username, role=data.get('role', 'user'), is_approved=True)
        u.set_password(password)
        db.session.add(u)
        db.session.commit()
        return jsonify({'message': 'User created'}), 201


@api_bp.route('/admin/settings', methods=['GET', 'PUT'])
@login_required
def admin_settings():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    keys = ['portal_name', 'guest_enabled', 'guest_default_hours', 'guest_max_hours', 'registration_enabled', 'vouchers_enabled']
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        for key in keys:
            if key not in data:
                continue
            setting = db.session.get(Setting, key) or Setting(key=key, value='')
            value = data[key]
            setting.value = str(value).lower() if isinstance(value, bool) else str(value)
            db.session.add(setting)
        _audit('settings_updated', ','.join(sorted(set(data) & set(keys))), current_user.id)
        db.session.commit()
    return jsonify({setting.key: setting.value for setting in Setting.query.filter(Setting.key.in_(keys)).all()}), 200


@api_bp.route('/admin/users/<int:user_id>/limits', methods=['PUT'])
@login_required
def update_user_limits(user_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'message': 'Not found'}), 404
    data = request.get_json(silent=True) or {}
    try:
        quota = data.get('quota_mb')
        user.quota_mb = None if quota in (None, '') else max(1, int(quota))
    except (TypeError, ValueError):
        return jsonify({'message': 'Invalid quota'}), 400
    start = data.get('time_window_start') or None
    end = data.get('time_window_end') or None
    if (start is None) != (end is None):
        return jsonify({'message': 'Both time-window values are required'}), 400
    try:
        if start:
            clock_time.fromisoformat(start)
            clock_time.fromisoformat(end)
    except ValueError:
        return jsonify({'message': 'Invalid time window'}), 400
    user.time_window_start = start
    user.time_window_end = end
    _audit('limits_updated', f'user_id={user.id}', current_user.id)
    db.session.commit()
    return jsonify({'message': 'Limits updated'}), 200

@api_bp.route('/admin/users/<int:user_id>/approve', methods=['POST'])
@login_required
def approve_user(user_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    u = User.query.get(user_id)
    if u:
        u.is_approved = True
        now = configured_now()
        
        # Instantly authenticate all devices linked to this user
        user_devices = Device.query.filter_by(user_id=u.id).all()
        for dev in user_devices:
            dev.is_authenticated = True
            dev.connected_at = now
            dev.last_seen = now
            network.add_device_to_ipset(mac_address=dev.mac_address, ip_address=dev.ip_address)
            
        db.session.commit()
        notify_users_changed()
        notify_devices_changed()
        
        # Broadcast approval so user's waiting screen transitions immediately
        try:
            socketio.emit('user_approved', {'user_id': u.id, 'username': u.username})
        except Exception:
            pass
            
        return jsonify({'message': 'Approved! Device access granted.'}), 200
    return jsonify({'message': 'Not found'}), 404


@api_bp.route('/admin/users/<int:user_id>/reset-password', methods=['POST'])
@login_required
def admin_reset_password(user_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'message': 'Not found'}), 404
    temporary_password = secrets.token_urlsafe(18)
    user.set_password(temporary_password)
    user.must_change_password = True
    _audit('password_reset', f'user_id={user.id}', current_user.id)
    db.session.commit()
    notify_all_async(f'Admin generated a password reset for account {user.username}')
    return jsonify({'message': 'Temporary password generated', 'temporary_password': temporary_password}), 200

@api_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    u = User.query.get(user_id)
    if not u:
        return jsonify({'message': 'User not found'}), 404
    if u.id == current_user.id:
        return jsonify({'message': 'Cannot delete your own admin account'}), 400
        
    # Unlink or kick associated devices
    try:
        from models import AuditLog
        user_devices = Device.query.filter_by(user_id=u.id).all()
        for dev in user_devices:
            dev.user_id = None
            dev.is_authenticated = False
            network.remove_device_from_ipset(mac_address=dev.mac_address, ip_address=dev.ip_address)
        AuditLog.query.filter_by(user_id=u.id).delete()
    except Exception:
        pass
        
    db.session.delete(u)
    db.session.commit()
    return jsonify({'message': 'User deleted'}), 200

# Voucher Management Endpoints
import string

def generate_voucher_code(length=8):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))

@api_bp.route('/admin/vouchers', methods=['GET', 'POST'])
@login_required
def admin_vouchers():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    now = configured_now()
    # Automatically erase expired vouchers from database and UI
    expired = Voucher.query.filter(Voucher.expires_at != None, Voucher.expires_at <= now).all()
    if expired:
        for ev in expired:
            if ev.used_by_device:
                dev = Device.query.filter_by(mac_address=ev.used_by_device).first()
                if dev:
                    dev.is_authenticated = False
                    network.remove_device_from_ipset(mac_address=ev.used_by_device, ip_address=dev.ip_address)
                else:
                    network.remove_device_from_ipset(mac_address=ev.used_by_device)
            db.session.delete(ev)
        db.session.commit()
        notify_devices_changed()

    if request.method == 'GET':
        vouchers = Voucher.query.order_by(Voucher.created_at.desc()).all()
        return jsonify([{
            'id': v.id, 
            'code': v.code, 
            'used_by_device': v.used_by_device,
            'duration_hours': v.duration_hours,
            'created_at': v.created_at.isoformat(), 
            'expires_at': v.expires_at.isoformat() if v.expires_at else None
        } for v in vouchers]), 200
        
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        count = data.get('count', 1)
        duration_hours = data.get('duration_hours', 24)
        
        codes = []
        for _ in range(count):
            code = generate_voucher_code()
            v = Voucher(
                code=code, 
                duration_hours=duration_hours,
                # Start expiration timer on first activation so unused vouchers don't expire prematurely
                expires_at=None 
            )
            db.session.add(v)
            codes.append(code)
            
        db.session.commit()
        return jsonify({'message': f'{count} vouchers created', 'codes': codes}), 201

@api_bp.route('/admin/vouchers/<int:v_id>', methods=['DELETE'])
@login_required
def delete_voucher(v_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    v = Voucher.query.get(v_id)
    if v:
        # If voucher was used by a device, kick device too
        if v.used_by_device:
            dev = Device.query.filter_by(mac_address=v.used_by_device).first()
            if dev:
                dev.is_authenticated = False
                network.remove_device_from_ipset(mac_address=v.used_by_device, ip_address=dev.ip_address)
        db.session.delete(v)
        db.session.commit()
        return jsonify({'message': 'Deleted'}), 200
    return jsonify({'message': 'Not found'}), 404
