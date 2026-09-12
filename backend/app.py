from flask import Flask, request, redirect
from extensions import db, socketio, login_manager, bcrypt
import network

def create_app(config_object=None):
    app = Flask(__name__, static_folder='../frontend/dist', static_url_path='/')
    app.config['SECRET_KEY'] = 'dev-secret-key-change-in-prod'
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nigel.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    if config_object:
        app.config.from_object(config_object)

    db.init_app(app)
    socketio.init_app(app)
    login_manager.init_app(app)
    bcrypt.init_app(app)

    # Register blueprints/routes here
    from routes import api_bp
    app.register_blueprint(api_bp, url_prefix='/api')

    @app.before_request
    def captive_portal_redirect():
        # Never intercept API calls, assets, or static resources
        if (request.path.startswith('/api/') or 
            request.path.startswith('/assets/') or 
            request.path in ('/favicon.ico', '/favicon.jpg', '/favicon.svg', '/icons.svg')):
            return None

        from models import Device
        client_ip = request.remote_addr
        mac_address = network.get_mac_from_ip(client_ip)

        # Check if device is authenticated
        is_auth = False
        if mac_address and not mac_address.startswith('ip-'):
            dev = Device.query.filter_by(mac_address=mac_address).first()
            if dev and dev.is_authenticated:
                is_auth = True
        if not is_auth and client_ip:
            dev = Device.query.filter_by(ip_address=client_ip).first()
            if dev and dev.is_authenticated:
                is_auth = True

        # Handle OS Captive Portal Connectivity Probes
        path = request.path.lower()
        host = (request.host or '').lower()

        # 1. Android probe
        if path in ('/generate_204', '/gen_204') or 'connectivitycheck.gstatic.com' in host:
            if is_auth:
                return ('', 204)
            return redirect('http://10.0.0.1:5000/', code=302)

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
            return redirect('http://10.0.0.1:5000/', code=302)

        # 3. Windows NCSI probe (clears "Action Needed" on Windows)
        if 'connecttest.txt' in path or 'msftconnecttest.com' in host:
            if is_auth:
                return ('Microsoft Connect Test', 200, {'Content-Type': 'text/plain'})
            return redirect('http://10.0.0.1:5000/', code=302)

        if 'ncsi.txt' in path or 'msftncsi.com' in host:
            if is_auth:
                return ('Microsoft NCSI', 200, {'Content-Type': 'text/plain'})
            return redirect('http://10.0.0.1:5000/', code=302)

        # Allow direct access to server IPs and hostnames
        host_without_port = request.host.split(':')[0]
        if host_without_port in ('10.0.0.1', '192.168.4.1', 'localhost', '127.0.0.1', 'nigel.local'):
            return None

        # If authenticated, do NOT redirect foreign requests (handled by iptables)
        if is_auth:
            return None

        # If unauthenticated and accessing external domain, redirect to captive portal
        return redirect('http://10.0.0.1:5000/', code=302)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_vue(path):
        # Serve Vue SPA if path doesn't match API
        return app.send_static_file('index.html')

    return app

if __name__ == '__main__':
    app = create_app()
    with app.app_context():
        db.create_all()
        
        from models import RegisteredService, User, Device
        # Seed default admin if no users exist
        if User.query.count() == 0:
            admin = User(username='admin', role='admin', is_approved=True)
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()

        # Seed default services if none exist
        if RegisteredService.query.count() == 0:
            defaults = [
                RegisteredService(name="Samba Share", description="Local file server", url="smb://10.0.0.1/share", icon="folder", check_port=445),
                RegisteredService(name="MiniDLNA", description="Media streaming", url="http://10.0.0.1:8200", icon="film", check_port=8200),
                RegisteredService(name="qBittorrent", description="Download manager", url="http://10.0.0.1:8080", icon="download", check_port=8080),
                RegisteredService(name="Plex", description="Media server", url="http://10.0.0.1:32400/web", icon="film", check_port=32400),
                RegisteredService(name="Jellyfin", description="Media server", url="http://10.0.0.1:8096", icon="film", check_port=8096)
            ]
            db.session.bulk_save_objects(defaults)
            db.session.commit()
            
        # Apply iptables rules
        network.apply_iptables_rules()

        # Restore previously authenticated devices from database into firewall
        auth_devices = Device.query.filter_by(is_authenticated=True).all()
        for d in auth_devices:
            network.add_device_to_ipset(mac_address=d.mac_address, ip_address=d.ip_address)
            
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

