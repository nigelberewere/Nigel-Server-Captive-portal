from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from models import User, Device, Voucher, Setting, RegisteredService
from extensions import db
import network
import datetime

api_bp = Blueprint('api', __name__)

@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    mac_address = data.get('mac_address') # Passed by captive portal frontend
    
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
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
