import argparse
import logging
import os
import secrets
import threading
import time
from datetime import datetime, time as clock_time
from zoneinfo import ZoneInfo
from pathlib import Path
from sqlalchemy import inspect, text
from urllib.parse import urlparse

from flask import Flask, request, redirect, jsonify
from flask_login import current_user
from extensions import db, socketio, login_manager, bcrypt
import network


def configured_now():
    timezone_name = os.environ.get('NIGEL_TIMEZONE', 'system')
    timezone = datetime.now().astimezone().tzinfo if timezone_name == 'system' else ZoneInfo(timezone_name)
    return datetime.now(timezone)

def create_app(config_object=None):
    app = Flask(__name__, static_folder='../frontend/dist', static_url_path='/')
    state_dir = Path(os.environ.get('NIGEL_STATE_DIR', '/var/lib/nigel-server'))
    state_dir.mkdir(parents=True, exist_ok=True)
    secret_path = Path(os.environ.get('NIGEL_SECRET_KEY_FILE', state_dir / 'secret.key'))
    if secret_path.exists():
        secret_key = secret_path.read_text(encoding='ascii').strip()
    else:
        secret_key = secrets.token_urlsafe(48)
        secret_path.write_text(secret_key + '\n', encoding='ascii')
        secret_path.chmod(0o600)
    app.config['SECRET_KEY'] = secret_key
    app.config['PORTAL_ORIGIN'] = os.environ.get('PORTAL_ORIGIN', 'http://localhost:5000').rstrip('/')
    portal_host = urlparse(app.config['PORTAL_ORIGIN']).hostname
    app.config['PORTAL_HOSTS'] = {host for host in (portal_host, 'localhost', '127.0.0.1') if host}
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nigel.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    if config_object:
        app.config.from_object(config_object)

    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins=app.config['PORTAL_ORIGIN'])
    login_manager.init_app(app)
    bcrypt.init_app(app)

    # Register blueprints/routes here
    from routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.before_request
    def captive_portal_redirect():
        if current_user.is_authenticated and getattr(current_user, 'must_change_password', False):
            allowed = {'/api/auth/password', '/api/auth/logout', '/api/auth/status'}
            if request.path.startswith('/api/') and request.path not in allowed:
                return jsonify({'message': 'Password change required'}), 403
        # Never intercept API calls, assets, or static resources
        if (request.path.startswith('/api/') or 
            request.path.startswith('/assets/') or 
            request.path in ('/favicon.ico', '/favicon.jpg', '/favicon.svg', '/icons.svg')):
            return None

        from models import Device, TrustedDevice
        client_ip = request.remote_addr
        mac_address = network.get_mac_from_ip(client_ip)

        # Check server-derived device identity and reject blocked devices.
        current_device = Device.query.filter_by(mac_address=mac_address).first() if mac_address else None
        trusted = TrustedDevice.query.filter_by(mac_address=mac_address).first() if mac_address else None
        is_auth = bool(trusted or (current_device and current_device.is_authenticated and not current_device.is_blocked))
        if current_user.is_authenticated and (not current_device or not current_device.is_blocked):
            is_auth = True
        # Handle OS Captive Portal Connectivity Probes
        path = request.path.lower()
        host = (request.host or '').lower()

        # 1. Android probe
        if path in ('/generate_204', '/gen_204') or 'connectivitycheck.gstatic.com' in host:
            if is_auth:
                return ('', 204)
            return redirect(f"{app.config['PORTAL_ORIGIN']}/", code=302)

        # 2. Apple iOS / macOS CNA probe (turns the "X" into "Done" / Blue Checkmark)
        if ('hotspot-detect.html' in path or 
            'success.html' in path or 
            'success.txt' in path or 
            'canonical.html' in path or 
            'captive.apple.com' in host or 
            'appleiphonecell.com' in host or 
            'airport.us' in host):
            if is_auth:
                return ('<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>', 200, {'Content-Type': 'text/html'})
            return redirect(f"{app.config['PORTAL_ORIGIN']}/", code=302)

        # 3. Windows NCSI probe (clears "Action Needed" on Windows)
        if 'connecttest.txt' in path or 'msftconnecttest.com' in host:
            if is_auth:
                return ('Microsoft Connect Test', 200, {'Content-Type': 'text/plain'})
            return redirect(f"{app.config['PORTAL_ORIGIN']}/", code=302)

        if 'ncsi.txt' in path or 'msftncsi.com' in host:
            if is_auth:
                return ('Microsoft NCSI', 200, {'Content-Type': 'text/plain'})
            return redirect(f"{app.config['PORTAL_ORIGIN']}/", code=302)

        # Allow direct access to server IPs and hostnames
        host_without_port = request.host.split(':')[0]
        if host_without_port in app.config['PORTAL_HOSTS'] or host_without_port == 'nigel.local':
            return None

        # If authenticated, do NOT redirect foreign requests (handled by iptables)
        if is_auth:
            return None

        # If unauthenticated and accessing external domain, redirect to captive portal
        return redirect(f"{app.config['PORTAL_ORIGIN']}/", code=302)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_vue(path):
        # Serve Vue SPA if path doesn't match API
        return app.send_static_file('index.html')

    return app


def expire_access_loop(app):
    from models import AuditLog, Device, Voucher
    while True:
        time.sleep(30)
        with app.app_context():
            now = configured_now()
            cutoff = now - __import__('datetime').timedelta(days=30)
            AuditLog.query.filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
            expired = Voucher.query.filter(
                Voucher.expires_at.isnot(None), Voucher.expires_at <= now,
                Voucher.used_by_device.isnot(None)
            ).all()
            changed = False
            devices = Device.query.filter_by(is_authenticated=True, is_blocked=False).all()
            for voucher in expired:
                device = Device.query.filter_by(mac_address=voucher.used_by_device).first()
                if device and device.is_authenticated:
                    device.is_authenticated = False
                    network.remove_device_from_ipset(mac_address=device.mac_address)
                    changed = True
            for device in devices:
                telemetry = network.get_device_telemetry(device.mac_address)
                device.data_used_mb = telemetry['data_used_mb']
                if device.access_expires_at and device.access_expires_at <= now:
                    device.is_authenticated = False
                    network.remove_device_from_ipset(mac_address=device.mac_address)
                    changed = True
                    continue
                user = device.user
                if not user:
                    continue
                if user.quota_mb is not None and device.data_used_mb >= user.quota_mb:
                    device.is_authenticated = False
                    network.remove_device_from_ipset(mac_address=device.mac_address)
                    changed = True
                    continue
                if user.time_window_start and user.time_window_end:
                    current = configured_now().time()
                    start = clock_time.fromisoformat(user.time_window_start)
                    end = clock_time.fromisoformat(user.time_window_end)
                    in_window = start <= current <= end if start <= end else current >= start or current <= end
                    if not in_window:
                        device.is_authenticated = False
                        network.remove_device_from_ipset(mac_address=device.mac_address)
                        changed = True
            if changed:
                db.session.commit()
                logging.getLogger(__name__).info('Expired voucher access removed')
            else:
                db.session.commit()


def start_expiry_worker(app):
    worker = threading.Thread(target=expire_access_loop, args=(app,), name='nigel-expiry', daemon=True)
    worker.start()


def initialize_database(app):
    with app.app_context():
        db.create_all()
        from models import RegisteredService, User, Device, TrustedDevice, Setting
        columns = {column['name'] for column in inspect(db.engine).get_columns('device')}
        if 'access_expires_at' not in columns:
            db.session.execute(text('ALTER TABLE device ADD COLUMN access_expires_at DATETIME'))
            db.session.commit()
        if User.query.count() == 0:
            password = secrets.token_urlsafe(18)
            admin = User(username='admin', role='admin', is_approved=True, must_change_password=True)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            password_file = Path(os.environ.get('NIGEL_ADMIN_PASSWORD_FILE', '/var/lib/nigel-server/admin-password'))
            password_file.parent.mkdir(parents=True, exist_ok=True)
            password_file.write_text(password + '\n', encoding='ascii')
            password_file.chmod(0o600)
            logging.getLogger(__name__).warning('Initial admin password written to %s', password_file)

        service_host = urlparse(app.config['PORTAL_ORIGIN']).hostname or 'localhost'
        default_services = [
                RegisteredService(name='Samba Share', description='Local file server', url=f'smb://{service_host}/share', icon='folder', check_port=445),
                RegisteredService(name='File Browser', description='Web file manager', url=f'http://{service_host}:80', icon='folder', check_port=80),
                RegisteredService(name='MiniDLNA', description='Media streaming', url=f'http://{service_host}:8200', icon='film', check_port=8200),
                RegisteredService(name='qBittorrent', description='Download manager', url=f'http://{service_host}:8080', icon='download', check_port=8080),
                RegisteredService(name='Plex', description='Media server', url=f'http://{service_host}:32400/web', icon='film', check_port=32400),
                RegisteredService(name='Jellyfin', description='Media server', url=f'http://{service_host}:8096', icon='film', check_port=8096),
            ]
        existing_services = {service.name for service in RegisteredService.query.all()}
        missing_services = [service for service in default_services if service.name not in existing_services]
        if missing_services:
            db.session.bulk_save_objects(missing_services)
            db.session.commit()
        defaults = {
            'portal_name': os.environ.get('PORTAL_NAME', 'Captive Portal'),
            'guest_enabled': 'false', 'guest_default_hours': '2', 'guest_max_hours': '24',
            'registration_enabled': 'true', 'vouchers_enabled': 'true'
        }
        for key, value in defaults.items():
            if db.session.get(Setting, key) is None:
                db.session.add(Setting(key=key, value=value))
        db.session.commit()

        network.apply_iptables_rules()
        for device in Device.query.filter_by(is_authenticated=True, is_blocked=False).all():
            network.add_device_to_ipset(mac_address=device.mac_address)
        for trusted in TrustedDevice.query.all():
            network.add_trusted_device(trusted.mac_address)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--cleanup', action='store_true', help='Remove Nigel firewall chains and ipsets')
    args = parser.parse_args()
    app = create_app()
    if args.cleanup:
        network.cleanup()
    else:
        initialize_database(app)
        start_expiry_worker(app)
        socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

