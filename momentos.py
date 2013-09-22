import os
import math
import logging
import webapp2
import cgi
import urllib
import jinja2
import json

from google.appengine.api import users
from google.appengine.ext import ndb
from google.appengine.ext import db
from google.appengine.api import images

import geobox

RADIUS = 6378100

GEOBOX_CONFIGS = (
  (4, 5, True),
  (3, 2, True),
  (3, 8, False),
  (3, 16, False),
  (2, 5, False),
)

def _earth_distance(lat1, lon1, lat2, lon2):
  lat1, lon1 = math.radians(float(lat1)), math.radians(float(lon1))
  lat2, lon2 = math.radians(float(lat2)), math.radians(float(lon2))
  return RADIUS * math.acos(math.sin(lat1) * math.sin(lat2) +
      math.cos(lat1) * math.cos(lat2) * math.cos(lon2 - lon1))

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'])

class UserPhoto(ndb.Model):
    """Model for storing user photos, since we can't get them directly"""
    userid = ndb.StringProperty(indexed=True)
    image = ndb.BlobProperty()

class Momento(ndb.Model):
    """Models a single momento"""
    author = ndb.UserProperty()
    date = ndb.DateTimeProperty(auto_now_add=True)
    text = ndb.StringProperty(indexed=False)
    location = ndb.GeoPtProperty()
    geoboxes = ndb.StringProperty(repeated=True)
    image = ndb.BlobProperty(default=None)
    thumbnail = ndb.BlobProperty(default=None)

    def serialize(self):
        d = {
            'key' : self.key.urlsafe(),
            'date' : self.date.isoformat(),
            'text' : self.text,
            'lat' : self.location.lat,
            'lon' : self.location.lon,
        }
        if self.author:
            d['author'] = self.author.nickname()
            up = UserPhoto.get_by_id(self.author.user_id())
            if up and up.image:
                logging.debug("Sending string for user ID " + self.author.user_id())
                d['userpic'] = '/userpic?user=' + self.author.user_id()
            else:
                d['userpic'] = '/static/default_userpic.jpg'
        else:
            d['author'] = None
        if self.thumbnail:
            d['thumbnail'] = '/momento_thumbnail?momento_id=' + self.key.urlsafe()
        else:
            d['thumbnail'] = None
        if self.image:
            d['image'] = '/momento_image?momento_id=' + self.key.urlsafe()
        else:
            d['image'] = None
        return d

    @classmethod
    def add(self, author, text, lat, lon, image):
        location = ndb.GeoPt(lat, lon)
        momento = Momento(author=author, text=text, location=location)

        if image:
            momento.image = db.Blob(image)
            thumbnail = images.resize(image, 100, 100)
            momento.thumbnail = db.Blob(thumbnail)

        all_boxes = []
        for (resolution, slice, use_set) in GEOBOX_CONFIGS:
          if use_set:
            all_boxes.extend(geobox.compute_set(lat, lon, resolution, slice))
          else:
            all_boxes.append(geobox.compute(lat, lon, resolution, slice))
        #logging.debug("Geoboxes " + str(all_boxes))
        momento.geoboxes = all_boxes

        momento.put()


    @classmethod
    def near_location(self, lat, lon, max_results, min_params):
        found_momentos = {}

        # Do concentric queries until the max number of results is reached.
        for params in GEOBOX_CONFIGS:
            if len(found_momentos) >= max_results:
                break
            if params < min_params:
                break

            resolution, slice, unused = params
            box = geobox.compute(lat, lon, resolution, slice)
            logging.debug("Searching for box=%s at resolution=%s, slice=%s", box, resolution, slice)
            query = Momento.query(Momento.geoboxes == box)
            results = query.fetch(100)
            logging.debug("Found %d results", len(results))

            # De-dupe results.
            for result in results:
                if result.key not in found_momentos:
                    found_momentos[result.key] = result

        # Now compute distances and sort by distance.
        momentos_by_distance = []
        for momento in found_momentos.itervalues():
            distance = _earth_distance(lat, lon, momento.location.lat, momento.location.lon)
            momentos_by_distance.append((distance, momento))

        momentos_by_distance.sort()

        # return momentos_by_distance
        return momentos_by_distance

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
        user_pos_lat = float(self.request.get('lat'))
        user_pos_lon = float(self.request.get('lon'))
        momentos = Momento.near_location(user_pos_lat, user_pos_lon, 25, (2, 0))

        self.response.headers['Content-Type'] = 'application/json'
        momento_list = [ m[1].serialize() for m in momentos ]
        obj = {
            'momentos': momento_list, 
          }
        self.response.out.write(json.dumps(obj))

class GetMomentosHtml(webapp2.RequestHandler):
    def get(self):
        user_pos_lat = float(self.request.get('lat'))
        user_pos_lon = float(self.request.get('lon'))
        momentos = Momento.near_location(user_pos_lat, user_pos_lon, 25, (2, 0))

        momento_list = [ m[1].serialize() for m in momentos ]
        template_values = {
            'momentos': momento_list, 
          }
        template = JINJA_ENVIRONMENT.get_template('momento_list.html')
        self.response.write(template.render(template_values))

class GetMomentoImage(webapp2.RequestHandler):
    def get(self):
        key = ndb.Key(urlsafe=self.request.get('momento_id'))
        momento = key.get()
        if momento and momento.image:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(momento.image)
        else:
            self.error(404)

class GetMomentoThumbnail(webapp2.RequestHandler):
    def get(self):
        key = ndb.Key(urlsafe=self.request.get('momento_id'))
        momento = key.get()
        if momento and momento.thumbnail:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(momento.thumbnail)
        else:
            self.error(404)

class PostMomento(webapp2.RequestHandler):
    def post(self):
        Momento.add(author = users.get_current_user(), 
            text = self.request.get('text'), 
            lat=float(self.request.get('lat')), 
            lon=float(self.request.get('lon')),
            image=self.request.get('image'))

        self.redirect('/debug')

class UserPhotoRequestHandler(webapp2.RequestHandler):
    def get(self):
        userid = self.request.get('user')
        logging.info("Looking up user photo for id " + userid)
        q = UserPhoto.query(UserPhoto.userid == userid)
        r = q.fetch(1)

        if len(r) < 1 or r[0] is None or r[0].image is None:
            self.error(404)
        else:
            self.response.headers['Content-Type'] = 'image/jpeg'
            self.response.out.write(r[0].image)

    def post(self):
        user = users.get_current_user()
        image = self.request.get('image')
        if user and image:
            logging.warn("Adding photo for userid " + user.user_id())
            logging.info("Resizing image")
            thumbnail = images.resize(image, 100, 100)
            logging.info("DB query")
            up = UserPhoto.get_or_insert(user.user_id())
            logging.info("Posting")
            up.userid = user.user_id()
            up.image = db.Blob(thumbnail)
            up.put()
            logging.info("Done!")

        self.redirect('/debug')

application = webapp2.WSGIApplication([
    ('/debug', DebugPage),
    ('/add_momento', PostMomento),
    ('/get_momentos', GetMomentos),
    ('/get_momentos_html', GetMomentosHtml),
    ('/momento_image', GetMomentoImage),
    ('/momento_thumbnail', GetMomentoThumbnail),
    ('/userpic', UserPhotoRequestHandler),
], debug=True)

