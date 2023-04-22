import enum
import os
import json

from flask import Flask, request, abort, jsonify
from flask_kerberos import requires_authentication, init_kerberos
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'file_zone.sqlite')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(db_path)
db = SQLAlchemy(app)

init_kerberos(app)


class StorableType(enum.Enum):
    DIRECTORY = 1
    TEXT = 2
    MULTI_MEDIA = 3


class Storable(db.Model):
    __tablename__ = 'storable'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    type = db.Column(db.Integer)
    size = db.Column(db.Integer)
    modified_at = db.Column(db.DateTime)
    parent_id = db.Column(db.Integer, db.ForeignKey('storable.id'))
    parent = db.relationship('Storable', remote_side=[id], backref='children')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'size': self.size,
            'modified_at': self.modified_at,
            'children': list(map(lambda x: x.to_dict(), self.children))
        }


class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)
    root = db.relationship('Storable', uselist=False, lazy=False)
    root_id = db.Column(db.Integer, db.ForeignKey('storable.id'))

    def to_dict(self):
        return {
            'id': self.id,
            'fullname': self.fullname,
            'email': self.email,
            'root': self.root.to_dict()
        }


app.app_context().push()
db.create_all()


@app.route('/login', methods=["POST"])
def login():
    data = json.loads(request.json)
    print(data)
    email = data.get("email", None)
    password = data.get("password", None)

    if not password and not email:
        return abort(404, "User not found")

    user = User.query.filter_by(email=email).first()

    if user is None:
        return abort(404, "User not found")

    if not check_password_hash(user.password, password):
        return abort(401, "Email or password not valid")

    token = None
    return jsonify({'user': user.to_dict(), 'token': token})


@app.route('/sign-up', methods=["POST"])
def sing_up():
    data = json.loads(request.json)
    print(data)

    email = data.get("email", None)
    fullname = data.get("fullname", None)
    password = data.get("password", None)

    if not password and not email and not fullname:
        return abort(404, "Error")

    if User.query.filter_by(email=email).first() is not None:
        return abort(400, 'Email already taken')

    hashed_password = generate_password_hash(password)
    user = User(email=email, password=hashed_password, fullname=fullname)
    root = Storable()
    root.name = fullname
    root.type = StorableType.DIRECTORY
    root.children = []
    user.root = root
    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User created successfully'})


@app.route('/logout')
@requires_authentication
def logout():
    username = request.remote_user
    # Invalidate the session token for the user
    return {'message': f'Goodbye {username}! Your session has been terminated.'}


if __name__ == '__main__':
    app.run(host="filezone.com", debug=True, ssl_context=('./certificate.crt', './private.key'))
