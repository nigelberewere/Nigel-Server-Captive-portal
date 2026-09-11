from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import User, Device, Voucher, Setting, RegisteredService
from extensions import db
import network
import datetime

api_bp = Blueprint('api', __name__)

@api_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if User.query.filter_by(username=username).first():
        return jsonify({'message': 'Username already exists'}), 400
        
    # By default, new registrations are NOT approved
    new_user = User(username=username, role='user', is_approved=False)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'Registration successful. Waiting for admin approval.'}), 201

@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    mac_address = data.get('mac_address') # Passed by captive portal frontend
    
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        # Admin is always approved, check is_approved for others
        if user.role != 'admin' and not user.is_approved:
            return jsonify({'message': 'Account pending admin approval.'}), 403
            
        login_user(user)
        
        # If MAC is provided, authenticate the device
        if mac_address:
            device = Device.query.filter_by(mac_address=mac_address).first()
            if not device:
                device = Device(mac_address=mac_address, ip_address=request.remote_addr)
                db.session.add(device)
            device.user_id = user.id
            device.is_authenticated = True
            device.connected_at = datetime.datetime.utcnow()
            db.session.commit()
            
            # Add to network ipset
            network.add_device_to_ipset(mac_address)
            
        return jsonify({'message': 'Logged in successfully', 'role': user.role}), 200
        
    return jsonify({'message': 'Invalid credentials'}), 401

@api_bp.route('/auth/logout', methods=['POST'])
@login_required
def logout():
    data = request.get_json()
    mac_address = data.get('mac_address')
    
    if mac_address:
        device = Device.query.filter_by(mac_address=mac_address).first()
        if device and device.user_id == current_user.id:
            device.is_authenticated = False
            db.session.commit()
            network.remove_device_from_ipset(mac_address)
            
    logout_user()
    return jsonify({'message': 'Logged out'}), 200

@api_bp.route('/auth/voucher', methods=['POST'])
def use_voucher():
    data = request.get_json()
    code = data.get('code')
    mac_address = data.get('mac_address')
    
    voucher = Voucher.query.filter_by(code=code).first()
    if voucher and (voucher.expires_at is None or voucher.expires_at > datetime.datetime.utcnow()):
        if voucher.used_by_device and voucher.used_by_device != mac_address:
             return jsonify({'message': 'Voucher already used by another device'}), 400
             
        device = Device.query.filter_by(mac_address=mac_address).first()
        if not device:
            device = Device(mac_address=mac_address, ip_address=request.remote_addr)
            db.session.add(device)
            
        device.is_authenticated = True
        device.connected_at = datetime.datetime.utcnow()
        voucher.used_by_device = mac_address
        db.session.commit()
        
        network.add_device_to_ipset(mac_address)
        return jsonify({'message': 'Voucher applied'}), 200
        
    return jsonify({'message': 'Invalid or expired voucher'}), 400

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
            'user': d.user.username if d.user else 'Guest'
        })
    return jsonify(res), 200

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
        data = request.get_json()
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'message': 'Username exists'}), 400
            
        u = User(username=data['username'], role=data.get('role', 'user'), is_approved=True)
        u.set_password(data['password'])
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
        db.session.commit()
        return jsonify({'message': 'Approved'}), 200
    return jsonify({'message': 'Not found'}), 404

@api_bp.route('/admin/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if current_user.role != 'admin':
        return jsonify({'message': 'Unauthorized'}), 403
    u = User.query.get(user_id)
    if u:
        db.session.delete(u)
        db.session.commit()
        return jsonify({'message': 'Deleted'}), 200
    return jsonify({'message': 'Not found'}), 404

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
        
    if request.method == 'GET':
        vouchers = Voucher.query.all()
        return jsonify([{
            'id': v.id, 'code': v.code, 'used_by_device': v.used_by_device,
            'created_at': v.created_at.isoformat(), 
            'expires_at': v.expires_at.isoformat() if v.expires_at else None
        } for v in vouchers]), 200
        
    if request.method == 'POST':
        data = request.get_json()
        count = data.get('count', 1)
        duration_hours = data.get('duration_hours', 24)
        
        codes = []
        for _ in range(count):
            code = generate_voucher_code()
            v = Voucher(
                code=code, 
                duration_hours=duration_hours,
                expires_at=datetime.datetime.utcnow() + datetime.timedelta(hours=duration_hours)
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
        db.session.delete(v)
        db.session.commit()
        return jsonify({'message': 'Deleted'}), 200
    return jsonify({'message': 'Not found'}), 404
