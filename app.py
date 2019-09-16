import datetime
import functools
import os
import re
import urllib

from flask import (Flask, abort, flash, Markup, redirect, render_template,
                   request, Response, session, url_for)
from markdown import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.extra import ExtraExtension
from micawber import bootstrap_basic, parse_html
from micawber.cache import Cache as OEmbedCache
from peewee import *
from playhouse.flask_utils import FlaskDB, get_object_or_404, object_list
from playhouse.sqlite_ext import *
from flask_sslify import SSLify

APP_DIR = os.path.dirname(os.path.realpath(__file__))
ADMIN_PASSWORD = 'put a password here'
DATABASE = 'sqliteext:///%s' % os.path.join(APP_DIR, 'blog.db')
DEBUG = False
SECRET_KEY = 'secret key lol'
SITE_WIDTH = 700

app = Flask(__name__)
app.config.from_object(__name__)
sslify = SSLify(app)

flask_db = FlaskDB(app)
database = flask_db.database

oembed_providers = bootstrap_basic(OEmbedCache())



# Projects Dict
projectArr = [
    "germination",
	"aliveandkicking",
    "pipegame",
    "mods",
	"music",
	
	"etc"
]


class Entry(flask_db.Model):
    title = CharField()
    slug = CharField(unique=True)
    tags = CharField(default='etc')
    content = TextField()
    published = True
    timestamp = DateTimeField(default=datetime.datetime.now, index=True)
    
    @property
    def html_content(self):
        hilite = CodeHiliteExtension(linenums=False, css_class='highlight')
        extras = ExtraExtension()
        markdown_content = markdown(self.content, extensions=[hilite, extras])
        oembed_content = parse_html(
            markdown_content,
            oembed_providers,
            urlize_all=True,
            maxwidth=app.config['SITE_WIDTH'])
        return Markup(oembed_content)
    
    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = re.sub('[^\w]+', '-', self.title.lower())
        ret = super(Entry, self).save(*args, **kwargs)

        # Store search content.
        self.update_search_index()
        return ret
    
    def update_search_index(self):
        search_content = '\n'.join((self.title, self.content))
        try:
            fts_entry = FTSEntry.get(FTSEntry.docid == self.id)
        except FTSEntry.DoesNotExist:
            FTSEntry.create(docid=self.id, content=search_content)
        else:
            fts_entry.content = search_content
            fts_entry.save()
    
    @classmethod
    def public(cls):
        # for now, all entries are public
        # why would I want a private blog post?
        return Entry.select()
    
    @classmethod
    def search(cls, query):
        words = [word.strip() for word in query.split() if word.strip()]
        if not words:
            return Entry.select().where(Entry.id == 0)
        else:
            search = ' '.join(words)
        
        return (Entry
            .select(Entry, FTSEntry.rank().alias('score'))
            .join(FTSEntry, on=(Entry.id == FTSEntry.docid))
            .where(
                (Entry.published == True) & (FTSEntry.match(search)))
            .order_by(SQL('score')))

    @classmethod
    def searchTags(cls, query):
        return ( Entry.select().where(Entry.tags == query) )


class FTSEntry(FTSModel):
    content = SearchField()
    
    class Meta:
        database = database

def login_required(fn):
    @functools.wraps(fn)
    def inner(*args, **kwargs):
        if session.get('logged_in'):
            return fn(*args, **kwargs)
        return redirect(url_for('login', next=request.path))
    return inner

@app.route('/login/', methods=["GET", "POST"])
def login():
    next_url = request.args.get('next') or request.form.get('next')
    if request.method == "POST" and request.form.get('password'):
        password = request.form.get('password')
        if password == app.config['ADMIN_PASSWORD']:
            session['logged_in'] = True
            session.permanent = True
            flash("You have logged in.", 'success')
            return redirect(next_url or url_for('index'))
        else:
            flash("Bad login.", 'danger')
    return render_template('login.html', next_url=next_url)

@app.route('/logout/', methods=["GET", "POST"])
def logout():
    if request.method == 'POST':
        session.clear()
        return redirect(url_for('index'))
    return render_template('logout.html')

@app.route('/')
def index():
    search_query = request.args.get('q')
    if search_query:
        query = Entry.search(search_query)
    else:
        query = Entry.public().order_by(Entry.timestamp.desc())
    return object_list('index.html', query, search = search_query)

@app.route('/blog')
def recentposts():
    search_query = request.args.get('q')
    if search_query:
        query = Entry.search(search_query)
    else:
        query = Entry.public().order_by(Entry.timestamp.desc())
    return object_list('recentposts.html', query, search = search_query)

@app.route('/projects/<project>')
def projects(project):
    if project in projectArr:
        return render_template('projects/' + project + '.html')
        # return object_list('projects/' + project + '.html', Entry.searchTags(project).order_by(Entry.timestamp.desc()), paginate_by=5)
    return render_template('projects/projects.html')

@app.route('/projects/')
def project():
    return render_template('projects/projects.html')

@app.route('/create/', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == "POST":
        if request.form.get('title') and request.form.get('content') and request.form.get('tags'):
            entry = Entry.create(
                title=request.form['title'],
                content = request.form['content'],
				tags = request.form['tags'])
            flash("Blog post created successfully.", 'success')
            if entry.published:
                return redirect(url_for('post', slug=entry.slug))
            else:
                return redirect(url_for('edit', slug=entry.slug))
        else:
            flash("Title, tags, and content are required.", 'danger')
    return render_template('create.html')

@app.route('/<slug>/edit/', methods=['GET', 'POST'])
@login_required
def edit(slug):
    entry = get_object_or_404(Entry, Entry.slug == slug)
    if request.method == "POST":
        if request.form.get('title') and request.form.get('content'):
            entry.title = request.form['title']
            entry.content = request.form['content']
            entry.tags = request.form['tags']
            entry.save()
            
            flash('Blog post saved.', 'success')
            if entry.published:
                return redirect(url_for('post', slug = entry.slug))
            else:
                return redirect(url_for('edit', slug = entry.slug))
        else:
            flash("Title and content are required.", 'danger')
    return render_template('edit.html', entry = entry)
    
@app.route('/<slug>/')
def post(slug):
    if session.get('logged_in'):
        query = Entry.select()
    else:
        query = Entry.public()
    entry = get_object_or_404(query, Entry.slug == slug)
    return render_template('post.html', entry=entry)

@app.template_filter('clean_querystring')
def clean_querystring(request_args, *keys_to_remove, **new_values):
    querystring = dict((key, value) for key, value in request_args.items())
    for key in keys_to_remove:
        querystring.pop(key, None)
    querystring.update(new_values)
    return urllib.urlencode(querystring)

@app.errorhandler(404)
def not_found(exc):
    return render_template('404.html'), 404 # ! Change to a special error page.

def main():
    database.create_tables([Entry, FTSEntry])
    app.run(host='0.0.0.0', port=443, debug=False, ssl_context=('../fullchain.pem', '../privkey.pem'))

if __name__ == '__main__':
    main()
