from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from flask_login import LoginManager
from flask_bcrypt import Bcrypt

db = SQLAlchemy()
socketio = SocketIO(async_mode='threading')
login_manager = LoginManager()
bcrypt = Bcrypt()
