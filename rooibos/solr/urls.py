from django.conf.urls.defaults import *
from views import *

urlpatterns = patterns('',
    url(r'^search/$', search, name='solr-search'),
    url(r'^search/(?P<collection>.*)/$', search, name='solr-search-collection'),
    url(r'^selected/$', selected, name='solr-selected'),
)
