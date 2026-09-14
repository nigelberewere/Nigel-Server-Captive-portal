from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import User, Device, Voucher, Setting, RegisteredService
from extensions import db, socketio
import network
import datetime

api_bp = Blueprint('api', __name__)

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
    mac_address = network.get_mac_from_ip(client_ip) or f"ip-{client_ip}"
    
    is_auth = False
    role = 'guest'
    username = None
    
    if current_user.is_authenticated:
        is_auth = True
        role = current_user.role
        username = current_user.username
    else:
        dev = None
        if mac_address and not mac_address.startswith('ip-'):
            dev = Device.query.filter_by(mac_address=mac_address).first()
        if not dev and client_ip:
            dev = Device.query.filter_by(ip_address=client_ip).first()
            
        if dev and dev.is_authenticated:
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
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password')
    client_ip = request.remote_addr
    mac_address = data.get('mac_address') or network.get_mac_from_ip(client_ip) or f"ip-{client_ip}"
    
    if not username or not password:
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
    if not device and client_ip:
        device = Device.query.filter_by(ip_address=client_ip).first()
        
    if not device:
        device = Device(mac_address=mac_address, ip_address=client_ip, user_id=new_user.id, is_authenticated=False)
        db.session.add(device)
    else:
        device.user_id = new_user.id
        device.is_authenticated = False

    db.session.commit()
    notify_users_changed()
    return jsonify({'message': 'Account requested! Waiting for admin approval.'}), 201

@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password')
    client_ip = request.remote_addr
    mac_address = data.get('mac_address') or network.get_mac_from_ip(client_ip) or f"ip-{client_ip}"
    
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        # Admin is always approved, check is_approved for normal users
        if user.role != 'admin' and not user.is_approved:
            return jsonify({'message': 'Account pending admin approval.'}), 403
            
        login_user(user)
        
        # Authenticate the device
        device = None
        if mac_address and not mac_address.startswith('ip-'):
            device = Device.query.filter_by(mac_address=mac_address).first()
        if not device and client_ip:
            device = Device.query.filter_by(ip_address=client_ip).first()
            
        if not device:
            device = Device(mac_address=mac_address, ip_address=client_ip)
            db.session.add(device)
        else:
            device.mac_address = mac_address
            device.ip_address = client_ip
            
        device.user_id = user.id
        device.is_authenticated = True
        device.connected_at = datetime.datetime.utcnow()
        device.last_seen = datetime.datetime.utcnow()
        db.session.commit()
        
        # Whitelist device in firewall (both MAC and IP)
        network.add_device_to_ipset(mac_address=mac_address, ip_address=client_ip)
        notify_devices_changed()
            
        return jsonify({'message': 'Logged in successfully', 'role': user.role, 'mac_address': mac_address}), 200
        
    return jsonify({'message': 'Invalid credentials'}), 401

@api_bp.route('/auth/logout', methods=['POST'])
def logout():
    data = request.get_json(silent=True) or {}
    client_ip = request.remote_addr
    mac_address = data.get('mac_address') or network.get_mac_from_ip(client_ip)
    
    if mac_address:
        device = Device.query.filter_by(mac_address=mac_address).first()
        if device:
            device.is_authenticated = False
            db.session.commit()
            network.remove_device_from_ipset(mac_address=mac_address, ip_address=device.ip_address)
            notify_devices_changed()
            
    if current_user.is_authenticated:
        logout_user()
    return jsonify({'message': 'Logged out'}), 200

@api_bp.route('/auth/voucher', methods=['POST'])
def use_voucher():
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip().upper()
    client_ip = request.remote_addr
    mac_address = data.get('mac_address') or network.get_mac_from_ip(client_ip) or f"ip-{client_ip}"
    
    if not code:
        return jsonify({'message': 'Please enter a voucher code'}), 400
        
    voucher = Voucher.query.filter_by(code=code).first()
    if not voucher:
        return jsonify({'message': 'Invalid voucher code'}), 400
        
    now = datetime.datetime.utcnow()
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
    if not device and client_ip:
        device = Device.query.filter_by(ip_address=client_ip).first()
        
    if not device:
        device = Device(mac_address=mac_address, ip_address=client_ip)
        db.session.add(device)
    else:
        device.mac_address = mac_address
        device.ip_address = client_ip
        
    device.is_authenticated = True
    device.connected_at = now
    device.last_seen = now
    db.session.commit()
    
    # Instantly allow device traffic through firewall
    network.add_device_to_ipset(mac_address=mac_address, ip_address=client_ip)
    notify_devices_changed()
    notify_vouchers_changed()
    
    return jsonify({
        'message': 'Voucher applied! Network access granted.',
        'mac_address': mac_address,
        'expires_at': voucher.expires_at.isoformat() if voucher.expires_at else None
    }), 200

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
        res.append({
            'mac_address': d.mac_address,
            'ip_address': d.ip_address,
            'hostname': d.hostname,
            'is_authenticated': d.is_authenticated,
            'user': d.user.username if d.user else ('Voucher' if d.is_authenticated else 'Unauthenticated')
        })
    return jsonify(res), 200

@api_bp.route('/admin/devices/<path:mac_address>/kick', methods=['POST', 'DELETE'])
@login_required
def kick_device(mac_address):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    device = Device.query.filter_by(mac_address=mac_address).first()
    if device:
        device.is_authenticated = False
        db.session.commit()
        network.remove_device_from_ipset(mac_address=mac_address, ip_address=device.ip_address)
        return jsonify({'message': f'Device {mac_address} kicked successfully'}), 200
        
    # Also remove from ipset directly
    network.remove_device_from_ipset(mac_address=mac_address)
    return jsonify({'message': f'Device {mac_address} removed from firewall'}), 200

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
            'is_approved': u.is_approved, 'created_at': u.created_at.isoformat()
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

@api_bp.route('/admin/users/<int:user_id>/approve', methods=['POST'])
@login_required
def approve_user(user_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    u = User.query.get(user_id)
    if u:
        u.is_approved = True
        now = datetime.datetime.utcnow()
        
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
import random
import string

def generate_voucher_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

@api_bp.route('/admin/vouchers', methods=['GET', 'POST'])
@login_required
def admin_vouchers():
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
        
    now = datetime.datetime.utcnow()
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
