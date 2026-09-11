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
        # Force a 302 Redirect for any intercepted traffic to trigger the OS popup.
        # If the requested host isn't 10.0.0.1:5000, iptables has caught them!
        if request.host != '10.0.0.1:5000' and not request.path.startswith('/api/'):
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
        
        # Seed default services if none exist
        from models import RegisteredService
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
            
    # Initialize ipset and apply iptables redirection rules
    network.init_ipset()
    network.apply_iptables_rules()
            
    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)

