from flask import Flask, flash, render_template, redirect, request, url_for, jsonify
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database_setup import Base, CatalogItem, User
from flask import session as login_session
import random, string

from oauth2client.client import flow_from_clientsecrets
from oauth2client.client import FlowExchangeError
import httplib2
import json
from flask import make_response
import requests

app = Flask(__name__)

CLIENT_ID = json.loads(
    open('client_secrets.json', 'r').read())['web']['client_id']
APPLICATION_NAME = "Item Catalog Application"

# Connect to Database and create database session
engine = create_engine('sqlite:///superitemcatalogwithusers.db')
Base.metadata.bind = engine

DBSession = sessionmaker(bind=engine)
session = DBSession()

# Create anti-forgery state token
@app.route('/login')
def showLogin():
    state = ''.join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session['state'] = state
    # return "The current session state is %s" % login_session['state']
    return render_template('login.html', STATE=state)

@app.route('/gconnect', methods=['POST'])
def gconnect():
    # Validate state token
    if request.args.get('state') != login_session['state']:
        response = make_response(json.dumps('Invalid state parameter.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets('client_secrets.json', scope='')
        oauth_flow.redirect_uri = 'postmessage'
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps('Failed to upgrade the authorization code.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ('https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s'
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, 'GET')[1])
    # If there was an error in the access token info, abort.
    if result.get('error') is not None:
        response = make_response(json.dumps(result.get('error')), 500)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token['sub']
    if result['user_id'] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Verify that the access token is valid for this app.
    if result['issued_to'] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers['Content-Type'] = 'application/json'
        return response

    stored_access_token = login_session.get('access_token')
    stored_gplus_id = login_session.get('gplus_id')
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps('Current user is already connected.'),
                                 200)
        response.headers['Content-Type'] = 'application/json'
        return response

    # Store the access token in the session for later use.
    login_session['access_token'] = credentials.access_token
    login_session['gplus_id'] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/oauth2/v1/userinfo"
    params = {'access_token': credentials.access_token, 'alt': 'json'}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()

    login_session['username'] = data['name']
    login_session['picture'] = data['picture']
    login_session['email'] = data['email']

    # see if user exists
    user_id = getUserID(login_session['email'])
    if not user_id:
        user_id = createUser(login_session)
        
    login_session['user_id'] = user_id
    output = ''
    output += '<h1>Welcome, '
    output += login_session['username']
    output += '!</h1>'
    output += '<img src="'
    output += login_session['picture']
    output += ' " style = "width: 300px; height: 300px;border-radius: 150px;-webkit-border-radius: 150px;-moz-border-radius: 150px;"> '
    flash("you are now logged in as %s" % login_session['username'])
    print "done!"
    return output


def createUser(login_session):
    newUser = User(name=login_session['username'], email=login_session['email'], picture=login_session['picture'])
    session.add(newUser)
    user = session.query(User).filter_by(email=login_session['email']).one()
    session.commit()
    return user.id


def getUserInfo(user_id):
    user = session.query(User).filter_by(id=user_id).one()
    return user


def getUserID(email):
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None
    

# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route('/gdisconnect')
def gdisconnect():
    access_token = login_session.get('access_token')
    if access_token is None:
        print 'Access Token is None'
        response = make_response(json.dumps('Current user not connected.'), 401)
        response.headers['Content-Type'] = 'application/json'
        return response
    print 'In gdisconnect access token is %s', access_token
    print 'User name is: '
    print login_session['username']
    url = 'https://accounts.google.com/o/oauth2/revoke?token=%s' % login_session['access_token']
    h = httplib2.Http()
    result = h.request(url, 'GET')[0]
    print 'result is '
    print result
    if result['status'] == '200':
        del login_session['access_token']
        del login_session['gplus_id']
        del login_session['username']
        del login_session['email']
        del login_session['picture']
        response = make_response(json.dumps('Successfully disconnected.'), 200)
        response.headers['Content-Type'] = 'application/json'
        return redirect('/catalog')
    else:
        response = make_response(json.dumps('Failed to revoke token for given user.', 400))
        response.headers['Content-Type'] = 'application/json'
        return response

# This function opens JSON endpoints
@app.route('/catalog/<int:catalog_id>/JSON')
def catalogItemsJSON(catalog_id):
    catalogItem = session.query(CatalogItem).filter_by(id=catalog_id).one()
    return jsonify(CatalogItem=catalogItem.serialize)


# This function is the Homepage for the item catalog.  It opens up the catalog.html page.
@app.route('/catalog')
@app.route('/')
def ListCatalog():
    items = session.query(CatalogItem)
    if 'username' not in login_session:
        return render_template('publiccatalog.html', items = items)
    else:
        return render_template('catalog.html', items = items)

# This function creates a new catalog item for the database.
@app.route('/catalog/create', methods=['GET', 'POST'])
def newCatalogItem():
    # If statement to allow only logged in personale to create items.
    if 'username' not in login_session:
        return redirect('/login')
    items = session.query(CatalogItem)
    if request.method == 'POST':
        # This if statement ceates a new name, description, or price for the new catalog item.
        newItem = CatalogItem(name=request.form['name'], description=request.form['description'], price=request.form['price'],
            user_id=login_session['user_id'])
        session.add(newItem)
        session.commit()
        return redirect(url_for('ListCatalog', items = items))
    else:
        return render_template('newitemmenu.html', items = items)


# Edit catalog item function

# This function selects catalog id to edit.
@app.route('/catalog/<int:catalog_id>/edit', methods=['GET', 'POST'])
def editCatalogItem(catalog_id):
    editedItem = session.query(CatalogItem).filter_by(id=catalog_id).one()
    # This if statement requires that only logged in people can edit items.
    if 'username' not in login_session:
        return redirect('/login')
    if request.method == 'POST':
        # This if statement selects name to edit from on editcatalogitem.html.
        if request.form['name']:
            editedItem.name = request.form['name']
        session.add(editedItem)
        session.commit()
        # This if statement selects the item Description to edit from on editcatalogitem.html.
        if request.form['description']:
            editedItem.description = request.form['description']
        session.add(editedItem)
        session.commit()
        # This if statement selects the item price to edit form on editcatalogitem.html.
        if request.form['price']:
            editedItem.price = request.form['price']
        session.add(editedItem)
        session.commit()
        return redirect(url_for('ListCatalog'))
    else:
        return render_template('editcatalogitem.html', catalog_id=catalog_id, i = editedItem)


# Function to delete catalog items

# Connects to specific catalog item id to delete.
@app.route('/catalog/<int:catalog_id>/delete', methods=['GET', 'POST'])
def deleteCatalogItem(catalog_id):
    itemToDelete = session.query(CatalogItem).filter_by(id=catalog_id).one()
    # This if statement allows only logged in people to delete items.
    if 'username' not in login_session:
        return redirect('/login')
    # This if statement selects specific item to delete.
    if request.method == 'POST':
        session.delete(itemToDelete)
        session.commit()
        return redirect(url_for('ListCatalog'))
    else:
        return render_template('deleteitem.html', item = itemToDelete)



if __name__ == '__main__':
    app.secret_key = 'Ly_YcGrphysXZpwnCCw0nnCm'
    app.debug = True
    app.run(host='0.0.0.0', port=5000)
