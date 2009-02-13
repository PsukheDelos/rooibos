from django.conf.urls.defaults import *
from django.contrib.syndication.views import feed
from django.views.generic.simple import direct_to_template
from views import *
from feeds import GroupFeed

feeds = {
    'collection': GroupFeed,
}

urlpatterns = patterns('',
    url(r'^groups/$', groups, name='data-groups'),
    url(r'^collection/(?P<groupname>[-\w]+)/$', group_raw, name='data-collection'),
    url(r'^record/(?P<recordname>[-\w]+)/$', record_raw, name='data-record'),
    url(r'^record/(?P<owner>[^/]+)/(?P<collection>[-\w]+)/(?P<recordname>[-\w]+)/$',
        record_raw, name='data-record'),
    url(r'^record/edit/(?P<recordname>[-\w]+)/$', record_edit, name='data-record-edit'),
    url(r'^record/edit/(?P<owner>[^/]+)/(?P<collection>[-\w]+)/(?P<recordname>[-\w]+)/$',
        record_edit, name='data-record-edit'),
    url(r'^selected/$', selected_records, name='data-selected'),
    (r'^feeds/(?P<url>.*)/$', feed, {'feed_dict': feeds}),
)
