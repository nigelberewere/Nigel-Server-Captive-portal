from flask_login import UserMixin
from datetime import datetime
from extensions import db, bcrypt

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user') # admin, user, guest, pending
    is_approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Quotas and Limits
    quota_mb = db.Column(db.Integer, nullable=True) # Max MB allowed per session or globally
    time_window_start = db.Column(db.String(5), nullable=True) # HH:MM
    time_window_end = db.Column(db.String(5), nullable=True) # HH:MM

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)


class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    mac_address = db.Column(db.String(17), unique=True, nullable=False)
    ip_address = db.Column(db.String(15), nullable=True)
    hostname = db.Column(db.String(120), nullable=True)
    
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref=db.backref('devices', lazy=True))
    
    connected_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    
    data_used_mb = db.Column(db.Float, default=0.0)
    is_blocked = db.Column(db.Boolean, default=False)
    is_authenticated = db.Column(db.Boolean, default=False)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    action = db.Column(db.String(100), nullable=False)
    details = db.Column(db.Text, nullable=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255), nullable=False)
    
class Voucher(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=True)
    duration_hours = db.Column(db.Integer, nullable=True)
    quota_mb = db.Column(db.Integer, nullable=True)
    used_by_device = db.Column(db.String(17), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class RegisteredService(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    url = db.Column(db.String(255), nullable=False)
    icon = db.Column(db.String(50), default='link')
    check_port = db.Column(db.Integer, nullable=True)  # Port to check if service is alive. If null, always show.

