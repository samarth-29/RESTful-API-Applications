import sqlite3
from datetime import datetime
import flask
from flask import jsonify, request, session, url_for, redirect, make_response, \
    render_template, abort, g, flash, _app_ctx_stack
from flask import Response
from flask_restful import reqparse
from werkzeug.security import safe_str_cmp
from flask_basicauth import BasicAuth


app = flask.Flask('discussion_forum')
app.config.from_object(__name__)
app.config.from_envvar('DISCUSSIONFORUMAPI_SETTINGS', silent=True)
app.config["DEBUG"] = True

DATABASE = '/tmp/DiscussionForum.db'
PER_PAGE = 30




# create database connection
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db


# close connection when not in use
@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


# create initial schema's
def create_schema():
    with app.app_context():
        db = get_db()
        with app.open_resource('createSchema.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


@app.cli.command('createschema')
def create_schema_command():
    """Initializes the database. and create schema"""
    create_schema()
    print('Database Schema Created')


# Insert dummy data into database
def insert_data():
    with app.app_context():
        db = get_db()
        with app.open_resource('insertData.sql', mode='r') as f:
            db.cursor().executescript(f.read())
        db.commit()


@app.cli.command('insertdata')
def insert_data_command():
    """Insert dummy data to database"""
    insert_data()
    print('Dummy data inserted to database')

# Initial operations completed ###


# A factory class
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d


# common query function
def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv


# User Authentication-Security
def authenticate(username, password):
    user = get_user_name(username)
    if user and safe_str_cmp(user.password, password):
        return user


def identity(payload):
    user_id = payload['identity']
    return get_user_id(user_id)

# Basic Authentication for REST API's
#pip install Flask-BasicAuth

class DiscussionForumBasicAuth(BasicAuth):
    def __init__(self, app=None):
        if app is not None:
            self.app = app
            self.init_app(app)
        else:
            self.app = None

    def check_credentials(self, username, password):
        if username is None:
            return None
        if password is None:
            return None
        db = get_db()
        user = query_db('select * from users where username = ?',[username], one=True)
        if user is None:
            return None

        if username == user.username and password == user.password:
            return True
        else:
            return None

basic_auth = DiscussionForumBasicAuth(app)
###### 1. user API's ######
# Find user_id using username
def get_user_name(username):
    rv = query_db('SELECT username FROM user WHERE username = ?',
                  [username], one=True)
    return rv[0] if rv else None


# Return user_id using the user_id
def get_user_id(_id):
    rv = query_db('SELECT user_id FROM user WHERE user_id = ?',
                  [_id], one=True)
    return rv[0] if rv else None

def check_authentication(username,password):
    rv = query_db('SELECT user_id FROM user WHERE username = ? and password = ?',
                  [username,password], one=True)
    return rv[0] if rv else None


# User registration
@app.route('/api/v1.0/user', methods=['POST'])
def register_user():
    parser = reqparse.RequestParser()
    parser.add_argument('username',
                        type=str,
                        required=True,
                        help="This field cannot be blank.")
    parser.add_argument('password',
                        type=str,
                        required=True,
                        help="This field cannot be blank.")
    data = parser.parse_args()

    if get_user_name(data['username']):
        return jsonify({"message":"user with that name already exists"}), 409

    connection = get_db()
    cursor = connection.cursor()
    query = "INSERT INTO user VALUES (NULL,?,?)"
    cursor.execute(query, (data['username'], data['password']))
    connection.commit()
    connection.close()
    resp = Response(status=201, mimetype='application/json')
    return resp


# Update User Info
@app.route('/api/v1.0/users/username', methods=['PUT'])
@basic_auth.required
def update_user(username):
        parser = reqparse.RequestParser()
        parser.add_argument('username',
                            type=str,
                            required=True,
                            help="This field cannot be blank.")
        parser.add_argument('password',
                            type=str,
                            required=True,
                            help="This field cannot be blank.")
        data = parser.parse_args()
        if get_user_name(username) is None:
            return jsonify({"message": "user with that name not found"}), 404

        if request.authorization.username != username:
            return jsonify({"message": "not authenticated user"}), 409

        connection = get_db()
        cursor = connection.cursor()

        query = "update user set username = ?, password = ? where username = ?"
        cursor.execute(query, (data['username'], data['password'], username))

        connection.commit()
        connection.close()

        return jsonify({"message": "user updated successfully"}), 200


####### Forum API's #######

# Find forumname based on name
def get_forum_name(name):
    rv = query_db('SELECT name FROM forum WHERE name = ?',
                  [name], one=True)
    return rv[0] if rv else None


# Find forum id
def get_forum_id():
    rv = query_db('SELECT forum_id FROM forum ORDER BY forum_id DESC',
                  one=True)
    return rv[0] if rv else None


# Find user_id using username
def get_forum_user_id(username):
    rv = query_db('SELECT user_id FROM user WHERE username = ?',
                  [username], one=True)
    return rv[0] if rv else None


# GET Operation on forums
@app.route('/api/v1.0/forums', methods=['GET'])
def get_forum():

    forums = query_db('''
           SELECT f.forum_id as id, f.name as name, u.username as creator 
           FROM forum f, user u 
           where f.user_id = u.user_id limit ?''', [PER_PAGE])

    forumdic = []
    if forums:
        for forum in forums:
            forumdic.append({"id":forum[0], "name":forum[1], "creator":forum[2]})
        return jsonify({'Forums': forumdic}), 200
    return {}


# POST Operation on forums
@basic_auth.required
@app.route('/api/v1.0/forums', methods=['POST'])
def post_forums():
    parser = reqparse.RequestParser()
    parser.add_argument('name',
                        type=str,
                        required=True,
                        help="This field cannot be blank.")
    data = parser.parse_args()
    username = request.authorization["username"]
    password = request.authorization["password"]
    uid = check_authentication(username,password)
    # return jsonify({"message": "Not authorized"}), 401
    if uid is None:
        abort(401)
    if get_forum_name(data['name']):
        return jsonify({"message":"forum with that name already exists"}), 409

    connection = get_db()
    cursor = connection.cursor()
    # user_id = get_forum_user_id(current_identity.username)
    user_id = get_forum_user_id(request.authorization.username)
    if user_id:
        query = "INSERT INTO forum VALUES (NULL,?,?)"
        cursor.execute(query, (data['name'], user_id))

    connection.commit()

    resp = Response(status=201, mimetype='application/json')

    forum_id = get_forum_id()
    if forum_id:
        resp.headers['Location'] = 'http://127.0.0.1:5000/forums/'+str(forum_id)
    connection.close()
    return resp


###### Thread API's ######

# Get forum_id for thread
def get_thread_forum_id(forumid):
    rv = query_db('SELECT forum_id FROM forum WHERE forum_id = ?',
                  [forumid], one=True)
    return rv[0] if rv else None


# Get thread Id
def get_thread_id():
    rv = query_db('SELECT thread_id FROM thread ORDER BY thread_id DESC',
                  one=True)
    return rv[0] if rv else None


# Find user_id using the username
def get_logged_in_user_id(username):
    if username is None:
        return None
    rv = query_db('SELECT user_id FROM user WHERE username = ?',
                  [username], one=True)
    return rv[0] if rv else None


# GET Operation on Thread
@app.route('/api/v1.0/forums/<forum_id>', methods=['GET'])
def get_threads(forum_id):
    threads = query_db('''select t.thread_id as id,t.title as title, 
                        (select p.timestamp from post p, thread t 
                        WHERE t.thread_id = p.thread_id 
                        and t.forum_id = ? order by p.post_id desc) as timestamp, 
                        (select u.username from post p, thread t, user u 
                        WHERE t.thread_id = p.thread_id and t.forum_id = ?  
                        and p.user_id = u.user_id order by p.post_id asc) as creator, t.title 
                        from thread t ''', [forum_id, forum_id])

    threadlist = []
    if threads:
        for thread in threads:
            threadlist.append({"id": thread[0], "title": thread[1], "creator": thread[3], "timestamp": thread[2]})
        return jsonify({'Threads': threadlist}), 200
    return {}, 404


# POST Operation in Thread
@basic_auth.required
@app.route('/api/v1.0/forums/<forum_id>', methods=['POST'])
def post_threads(forum_id):

        # parser to parse the payload
        parser = reqparse.RequestParser()
        parser.add_argument('title',
                            type=str,
                            required=True,
                            help="This field cannot be blank.")
        parser.add_argument('text',
                            type=str,
                            required=True,
                            help="This field cannot be blank.")

        data = parser.parse_args()

        if get_thread_forum_id(forum_id) is None:
            return jsonify({"message":"forum does not exist"}), 404

        connection = get_db()
        cursor = connection.cursor()

        query = "INSERT INTO thread VALUES (NULL,?,?)"
        cursor.execute(query, (forum_id, data['title']))
        connection.commit()

        # Add current logged in user
        # user_id = Threadname.get_user_id(current_identity.username)
        username = request.authorization.username
        if username is None:
            return jsonify({"message": "Not authorized"}), 401

        user_id = get_logged_in_user_id(request.authorization.username)
        thread_id = get_thread_id()

        if thread_id:
            query = "INSERT INTO post VALUES (NULL,?,?,?,?)"
            cursor.execute(query, (thread_id, user_id, data['text'], datetime.now()))
            connection.commit()

            resp = Response(status=201, mimetype='application/json')
            resp.headers['Location'] = 'http://127.0.0.1:5000/forums/' + str(forum_id) +'/'+str(thread_id)

        connection.close()
        return resp


##### POST API's ######
# Get thread Id using forum Id
def get_post_thread_id(forum_id, thread_id):
    rv = query_db('SELECT thread_id FROM thread WHERE thread_id = ? and forum_id = ?',
                  [forum_id, thread_id], one=True)
    return rv[0] if rv else None
# Find user_id using the username
def get_logged_in_user_id(username):
    rv = query_db('SELECT user_id FROM user WHERE username = ?',
                  [username], one=True)
    return rv[0] if rv else None

# GET operations for POST'S
@app.route('/api/v1.0/forums/​forum_id/<thread_id>', methods=['GET'])
def get_posts(forum_id, thread_id):

    if get_post_thread_id(forum_id, thread_id) is None:
        return jsonify({"message":"forum / thread does not exist"}), 404

    posts = query_db('''
                    SELECT u.username as author, p.text, p.timestamp 
                    FROM post p, thread t, user u 
                    where t.thread_id = p.thread_id 
                    and t.thread_id = ? and t.forum_id = ?  
                    and u.user_id  = p.user_id 
                    order by timestamp desc''', [thread_id, forum_id])

    postlist = []
    if posts:
        for post in posts:
             postlist.append({"author": post[0], "text": post[1], "timestamp": post[2]})
        return jsonify({'Posts': postlist}), 200
    return {}, 404

# POST operations for POST'S
@basic_auth.required
@app.route('/api/v1.0/forums/​forum_id/<thread_id>', methods=['POST'])
def post_posts(self, forum_id, thread_id):
    parser = reqparse.RequestParser()
    parser.add_argument('text',
                        type=str,
                        required=True,
                        help="This field cannot be blank.")
    data = parser.parse_args()
    if get_post_thread_id(forum_id, thread_id) is None:
        return jsonify({"message": "forum / thread does not exist"}), 404
    connection = sqlite3.connect('data.db')
    cursor = connection.cursor()
    user_id = get_logged_in_user_id(request.authorization.username)
    query = "INSERT INTO post VALUES (NULL,?,?,?,?)"
    cursor.execute(query, (thread_id, user_id, data['text'], datetime.now()))
    connection.commit()
    resp = Response(status=201, mimetype='application/json')
    connection.close()
    return resp
app.run()
