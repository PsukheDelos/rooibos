from django.db.models import Count
from django.core.cache import cache
from django.shortcuts import render_to_response, get_object_or_404
from django.http import HttpResponse, HttpResponseRedirect, Http404
from django.template import RequestContext
from django.template.loader import render_to_string
from django.core.urlresolvers import reverse
from . import SolrIndex
from rooibos.access import filter_by_access, accessible_ids, accessible_ids_list
from rooibos.util import safe_int, json_view
from rooibos.data.models import Field, Collection, FieldValue
from rooibos.storage.models import Storage
from rooibos.ui import update_record_selection, clean_record_selection_vars
import re
import copy


class SearchFacet(object):
    
    def __init__(self, name, label):
        self.name = name
        self.label = label
        
    def process_criteria(self, criteria, *args, **kwargs):
        return criteria
        
    def set_result(self, facets):
        # break down dicts into tupels
        if hasattr(facets, 'items'):
            self.facets = facets.items()
        else:
            self.facets = facets
            
    def clean_result(self, hits):
        # sort facet items and remove the ones that match all hits
        self.facets = filter(lambda f: f[1] < hits, self.facets)
        self.facets = sorted(self.facets, key=lambda f: len(f) > 2 and f[2] or f[0])
        
    def or_available(self):
        return True


class StorageSearchFacet(SearchFacet):

    _storage_facet_re = re.compile(r'^s(\d+)-(.+)$')
   
    def __init__(self, name, label, available_storage):
        super(StorageSearchFacet, self).__init__(name, label)
        self.available_storage = available_storage
 
    def process_criteria(self, criteria, user, *args, **kwargs):
        criteria = '|'.join('s*-%s' %s for s in criteria.split('|'))
        return user.is_superuser and criteria \
            or '(%s) AND (%s)' % (' '.join('s%s-*' % s for s in self.available_storage), criteria)

    def set_result(self, facets):
        result = {}
        if facets:
            for f in facets.keys():
                m = StorageSearchFacet._storage_facet_re.match(f)
                if m and int(m.group(1)) in self.available_storage:
                    result[m.group(2)] = None  # make facet available, but without frequency count            
        super(StorageSearchFacet, self).set_result(result)


class CollectionSearchFacet(SearchFacet):
    
    def set_result(self, facets):
        result = []
        for id, title in Collection.objects.filter(id__in=map(int, facets.keys())).values_list('id', 'title'):
            result.append((id, facets[str(id)], title))
        super(CollectionSearchFacet, self).set_result(result)


class ExactValueSearchFacet(SearchFacet):
    
    _special = re.compile(r'(\+|-|&&|\|\||!|\(|\)|\{|}|\[|\]|\^|"|~|\*|\?|:|\\)')
    
    def __init__(self, name):
        prefix, name = ([None] + name[:-2].split('.'))[-2:]
        if prefix:
            field = Field.objects.get(standard__prefix=prefix, name=name)
        else:
            field = Field.objects.get(standard=None, name=name)
        super(ExactValueSearchFacet, self).__init__(name, field.label)
    
    def process_criteria(self, criteria, *args, **kwargs):
        return '"' + self._special.sub(r'\\\1', criteria) + '"'

    def or_available(self):
        return False


def _generate_query(search_facets, user, collection, criteria, keywords, selected, *exclude):

    fields = {}
    for c in criteria:
        if c in exclude:
            continue
        (f, o) = c.split(':', 1)
        if f.startswith('-'):
            f = 'NOT ' + f[1:]
        fname = f.rsplit(' ',1)[-1]
        
        # create exact match criteria on the fly if needed
        if fname.endswith('_s') and not search_facets.has_key(fname):
            search_facets[fname] = ExactValueSearchFacet(fname)
        
        o = search_facets[fname].process_criteria(o, user)
        fields.setdefault(f, []).append('(' + o.replace('|', ' OR ') + ')')
    fields = map(lambda (name, crit): '%s:(%s)' % (name, (name.startswith('NOT ') and ' OR ' or ' AND ').join(crit)),
                 fields.iteritems())
    
    def build_keywords(q, k):
        k = k.lower()
        if k == 'and' or k == 'or':
            return q + ' ' + k.upper()
        elif q.endswith(' AND') or q.endswith(' OR'):
            return q + ' ' + k
        else:
            return q + ' AND ' + k
    
    if keywords: keywords = reduce(build_keywords, keywords.split())
    
    query = ''
    if fields:    
        query = ' AND '.join(fields)
    if keywords:    
        query = query and '%s AND (%s)' % (query, keywords) or '(%s)' % keywords
    if not query:
        query = '*:*'
    if collection:
        query = 'collections:%s AND %s' % (collection.id, query)
    if selected:
        query = 'id:(%s) AND %s' % (' '.join(map(str, selected)), query)
        
    if not user.is_superuser:
        groups = ' '.join(map(str, accessible_ids_list(user, Collection)))
        c = []
        if groups: c.append('collections:(%s)' % groups)
        if user.id: c.append('owner:%s' % user.id)
        if c:
            query = '(%s) AND %s' % (' OR '.join(c), query)
        else:
            query = 'id:"-1"'
    
    return query


def selected(request):
    return search(request, selected=True)

def search(request, id=None, name=None, selected=False, json=False):
    collection = id and get_object_or_404(filter_by_access(request.user, Collection), id=id) or None
    
    update_record_selection(request)
    
    templates = dict(l='list')
    
    viewmode = request.GET.get('v', 'i')
    if viewmode == 'l':
        pagesize = max(min(safe_int(request.GET.get('ps', '100'), 100), 200), 5)
    else:
        pagesize = max(min(safe_int(request.GET.get('ps', '50'), 50), 100), 5)
    page = safe_int(request.GET.get('p', '1'), 1)
    sort = request.GET.get('s', 'score desc')
    criteria = request.GET.getlist('c')
    orquery = request.GET.get('or', None)
    remove = request.GET.get('rem', None)
    if remove: criteria.remove(remove)
    keywords = request.GET.get('kw', '')
    
    if request.GET.has_key('action'):
        page = safe_int(request.GET.get('op', '1'), 1)
    
    if selected:
        selected = request.session.get('selected_records', ())
    
    available_storage = accessible_ids_list(request.user, Storage)
    
    exclude_facets = ['identifier']

    fields = Field.objects.filter(standard__prefix='dc').exclude(name__in=exclude_facets)
 
    search_facets = [SearchFacet('tag', 'Tags')] + [SearchFacet(field.name + '_t', field.label) for field in fields]
    search_facets.append(StorageSearchFacet('resolution', 'Image size', available_storage))
    search_facets.append(StorageSearchFacet('mimetype', 'Media type', available_storage))
    search_facets.append(CollectionSearchFacet('collections', 'Collection'))
    # convert to dictionary
    search_facets = dict((f.name, f) for f in search_facets)

    query = _generate_query(search_facets, request.user, collection, criteria, keywords, selected, remove)
       
    s = SolrIndex()
    
    if json:
        return_facets = []
    else:
        return_facets = search_facets.keys()
    
    (hits, records, facets) = s.search(query, sort=sort, rows=pagesize, start=(page - 1) * pagesize,
                                       facets=return_facets, facet_mincount=1, facet_limit=100)

    if json:
        return render_to_string('results_bare_' + templates.get(viewmode, 'icons') + '.html',
                              {'records': records,
                               'selectable': True,},
                              context_instance=RequestContext(request))

    for f in search_facets:
        search_facets[f].set_result(facets.get(f))
    
    orfacet = None
    if orquery:
        (f, v) = orquery.split(':', 1)
        orfacets = s.search(_generate_query(search_facets, request.user, collection, criteria, keywords, selected,
                                            remove, orquery),
                            rows=0, facets=[f], facet_mincount=1, facet_limit=100)[2]
        orfacet = copy.copy(search_facets[f])
        orfacet.label = '%s in %s or...' % (v.replace("|", " or "), orfacet.label)
        orfacet.set_result(orfacets[f])
    
    if collection:
        url = reverse('solr-search-collection', kwargs={'id': collection.id, 'name': collection.name})
    elif selected:
        url = reverse('solr-selected')
    else:
        url = reverse('solr-search')
    
    q = request.GET.copy()
    q = clean_record_selection_vars(q)
    q.pop('or', None)
    q.pop('rem', None)
    q.pop('action', None)
    q.pop('p', None)
    q.pop('op', None)
    q.setlist('c', criteria)
    hiddenfields = [('op', page)]
    for f in q:
        if f != 'kw':
            for l in q.getlist(f):
                hiddenfields.append((f, l))
    qurl = q.urlencode()
    q.setlist('c', filter(lambda c: c != orquery, criteria))
    qurl_orquery = q.urlencode()
    limit_url = "%s?%s%s" % (url, qurl, qurl and '&' or '')
    limit_url_orquery = "%s?%s%s" % (url, qurl_orquery, qurl_orquery and '&' or '')
    prev_page_url = None
    next_page_url = None
    
    if page > 1:
        q['p'] = page - 1
        prev_page_url = "%s?%s" % (url, q.urlencode())
    if page < (hits - 1) / pagesize + 1:
        q['p'] = page + 1
        next_page_url = "%s?%s" % (url, q.urlencode())


    def readable_criteria(c):
        (f, o) = c.split(':', 1)
        o = o.replace('|', ' or ')
        if f.startswith('-'):
            return (c, '%s not in %s' % (o, search_facets[f[1:]].label), False)
        else:
            return (c, '%s in %s' % (o, search_facets[f].label), search_facets[f].or_available())

    
    # sort facets by label
    facets = sorted(search_facets.values(), key=lambda f: f.label)
    
    # clean facet items
    for f in facets:
        f.clean_result(hits)
    
    # remove facets with only no filter options
    facets = filter(lambda f: len(f.facets) > 0, facets)    

    return render_to_response('results_' + templates.get(viewmode, 'icons') + '.html',
                              {'criteria': map(readable_criteria, criteria),
                               'query': query,
                               'keywords': keywords,
                               'hiddenfields': hiddenfields,
                               'records': records,
                               'hits': hits,
                               'page': page,
                               'pages': (hits - 1) / pagesize + 1,
                               'prev_page': prev_page_url,
                               'next_page': next_page_url,
                               'reset_url': url,
                               'limit_url': limit_url,
                               'limit_url_orquery': limit_url_orquery,
                               'facets': facets,
                               'orfacet': orfacet,
                               'orquery': orquery,},
                              context_instance=RequestContext(request))


@json_view
def search_json(request, id=None, name=None, selected=False):
    return dict(html=search(request, id, name, selected, json=True))
    

def browse(request, id=None, name=None):
    
    collections = filter_by_access(request.user, Collection).order_by('title')
    if not collections:
        raise Http404()
    
    if request.GET.has_key('c'):
        collection = get_object_or_404(collections, name=request.GET['c'])
        return HttpResponseRedirect(reverse('solr-browse-collection',
                                            kwargs={'id': collection.id, 'name': collection.name}))
    
    collection = id and get_object_or_404(collections, id=id) or collections[0]

    fields = cache.get('browse_fields_%s' % collection.id)
    if fields:
        fields = list(Field.objects.filter(id__in=fields))
    else:
        fields = list(Field.objects.filter(fieldvalue__record__collection=collection).distinct())
        cache.set('browse_fields_%s' % collection.id, [f.id for f in fields], 60)        
    if not fields:
        raise Http404()
        
    if request.GET.has_key('f'):
        field = get_object_or_404(Field, name=request.GET['f'], id__in=(f.id for f in fields))
    else:
        field = fields[0]
        
    values = FieldValue.objects.filter(field=field, record__collection=collection).values('value').annotate(freq=Count('value', distinct=False)).order_by('value')
    
    if request.GET.has_key('s'):
        start = values.filter(value__lt=request.GET['s']).count() / 50 + 1
        return HttpResponseRedirect(reverse('solr-browse-collection',
                                            kwargs={'id': collection.id, 'name': collection.name}) +
                                    "?f=%s&page=%s" % (field.name, start))
    
    return render_to_response('browse.html',
                              {'collections': collections,
                               'selected_collection': collection and collection or None,
                               'fields': fields,
                               'selected_field': field,
                               'values': values,},
                              context_instance=RequestContext(request))


def overview(request):
    
    collections = filter_by_access(request.user, Collection).order_by('title').annotate(num_records=Count('records'))
    
    return render_to_response('overview.html',
                              {'collections': collections,},
                              context_instance=RequestContext(request))