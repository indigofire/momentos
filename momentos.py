import os
import webapp2
import cgi
import urllib
import jinja2
import json

from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext import db
from google.appengine.api import images


JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class Momento(ndb.Model):
    """Models an individual Guestbook entry with author, content, and date."""
    author = ndb.UserProperty()
    date = ndb.DateTimeProperty(auto_now_add=True)
    text = ndb.StringProperty(indexed=False)
    location = ndb.GeoPtProperty()
    image = ndb.BlobProperty(default=None)
    thumbnail = ndb.BlobProperty(default=None)

    def serialize(self):
        d = {
            'key' : self.key.urlsafe(),
            'date' : self.date.isoformat(),
            'text' : self.text,
            'location' : self.location,
            'thumbnail' : self.thumbnail,
        }
        if self.author:
            d['author'] = self.author.nickname()
        else:
            d['author'] = None
        return d


class DebugPage(webapp2.RequestHandler):

    def get(self):
        if users.get_current_user():
            url = users.create_logout_url(self.request.uri)
            url_linktext = 'Logout'
        else:
            url = users.create_login_url(self.request.uri)
            url_linktext = 'Login'

        template_values = {
            'url': url,
            'url_linktext': url_linktext,
        }

        template = JINJA_ENVIRONMENT.get_template('debug.html')
        self.response.write(template.render(template_values))


class GetMomentos(webapp2.RequestHandler):
    def get(self):
        momento_query = Momento.query()
        momentos = momento_query.fetch(20)
        self.response.headers['Content-Type'] = 'application/json'
        momento_list = [ m.serialize() for m in momentos ]
        obj = {
            'momentos': momento_list, 
          }
        self.response.out.write(json.dumps(obj))

class GetMomentoImage(webapp2.RequestHandler):
    def get(self):
        key = ndb.Key(urlsafe=self.request.get('momento_id'))
        momento = key.get()
        if momento and momento.image:
            self.response.headers['Content-Type'] = 'image/png'
            self.response.out.write(momento.image)
        else:
            self.error(404)

class PostMomento(webapp2.RequestHandler):
    def post(self):
        momento = Momento()

        if users.get_current_user():
            momento.author = users.get_current_user()

        momento.text = self.request.get('text')
        image = self.request.get('image')
        if image:
            momento.image = db.Blob(image)
            thumbnail = images.resize(image, 100, 100)
            momento.thumbnail = db.Blob(thumbnail)
        momento.put()

        self.redirect('/debug')

application = webapp2.WSGIApplication([
    ('/debug', DebugPage),
    ('/add_momento', PostMomento),
    ('/get_momentos', GetMomentos),
    ('/momento_image', GetMomentoImage),
], debug=True)

