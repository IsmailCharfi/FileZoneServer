import enum
import os
import json
import shutil
from datetime import datetime

from flask import Flask, request, abort, jsonify, send_file
from flask_kerberos import requires_authentication, init_kerberos
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
db_path = os.path.join(basedir, 'file_zone.sqlite')

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///{}'.format(db_path)
db = SQLAlchemy(app)

init_kerberos(app)


class StorableType(enum.Enum):
    DIRECTORY = 1
    FILE = 2


class Storable(db.Model):
    __tablename__ = 'storable'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255))
    type = db.Column(db.Integer)
    size = db.Column(db.Integer)
    modified_at = db.Column(db.DateTime)
    parent_id = db.Column(db.Integer, db.ForeignKey('storable.id'))
    parent = db.relationship('Storable', remote_side=[id], backref="children")

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'size': self.get_size(),
            'modified_at': self.modified_at.strftime("%Y-%m-%d %H:%M:%S"),
            'children': list(map(lambda x: x.to_dict(), self.children))
        }

    def path(self):
        if not self.parent and self.owner:
            return f"./uploads/{self.owner.email}"

        return self.parent.path() + f"/{self.name}"

    def get_owner(self):
        if self.owner:
            return self.owner
        else:
            return self.parent.get_owner()

    def get_size(self):
        if self.size:
            return self.size
        else:
            return sum(map(lambda x: x.get_size(), self.children))


class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    fullname = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(250), nullable=False)
    root = db.relationship('Storable', uselist=False, lazy=False, backref=db.backref('owner', uselist=False))
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
    root.type = StorableType.DIRECTORY.value
    root.children = []
    root.modified_at = datetime.now()
    user.root = root
    root.owner = user

    os.mkdir(root.path())

    db.session.add(user)
    db.session.commit()

    return jsonify({'message': 'User created successfully'})


@app.route('/<int:_id>/add-file', methods=["POST"])
def add_file(_id):
    folder = Storable.query.filter_by(id=_id).first()

    if not folder or folder.type != StorableType.DIRECTORY.value:
        return abort(404, "Not directory")

    file = request.files['file']

    content = file.read()

    created_file = Storable()
    created_file.parent = folder
    created_file.name = secure_filename(file.filename)
    created_file.size = len(content)
    created_file.type = StorableType.FILE.value
    created_file.modified_at = datetime.now()

    with open(created_file.path(), 'wb') as f:
        f.write(content)

    db.session.add(created_file)
    db.session.commit()

    return jsonify({})


@app.route('/<int:_id>/add-folder', methods=["POST"])
def add_folder(_id):
    folder = Storable.query.filter_by(id=_id).first()

    if not folder or folder.type != StorableType.DIRECTORY.value:
        return abort(404, "Not directory")

    data = json.loads(request.json)

    created_folder = Storable()
    created_folder.parent = folder
    created_folder.name = data.get("name", None)
    created_folder.type = StorableType.DIRECTORY.value
    created_folder.modified_at = datetime.now()

    os.mkdir(created_folder.path())

    db.session.add(created_folder)
    db.session.commit()

    return jsonify({})


@app.route('/users/<int:_id>/root', methods=["GET"])
def get_root(_id):
    user = User.query.filter_by(id=_id).first()

    if not user:
        return abort(404, "Not Found")

    return jsonify(user.root.to_dict())


@app.route('/<int:_id>', methods=["DELETE"])
def delete_storable(_id):
    storable = Storable.query.filter_by(id=_id).first()

    if not storable:
        return abort(404, "NOT FOUNT")

    path = storable.path()
    db.session.delete(storable)
    db.session.commit()

    if os.path.isfile(path):
        os.remove(path)
    else:
        shutil.rmtree(path)

    return jsonify({})


@app.route('/<int:_id>/content', methods=["GET"])
def download(_id):
    storable = Storable.query.filter_by(id=_id).first()

    if not storable or not storable.type == StorableType.FILE.value:
        return abort(404, "NOT A FILE")

    return send_file(storable.path(), as_attachment=True)


if __name__ == '__main__':
    app.run(host="filezone.com", debug=True, ssl_context=('./certificate.crt', './private.key'))
