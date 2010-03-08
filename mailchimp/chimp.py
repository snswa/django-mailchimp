from mailchimp.chimpy.chimpy import Connection as BaseConnection
from mailchimp.utils import Cache, wrap, build_dict
from mailchimp.exceptions import CampaignDoesNotExist, ListDoesNotExist, ConnectionFailed, TemplateDoesNotExist
from mailchimp.constants import *
import datetime


class BaseChimpObject(object):
    _attrs = ()
    _methods = ()
    
    def __init__(self, master, info):
        self.master = master
        for attr in self._attrs:
            setattr(self, attr, info[attr])
            
        base = self.__class__.__name__.lower()
        
        for method in self._methods:
            setattr(self, method, wrap(base, self.master.con, method, self.id))
        
        
class Campaign(BaseChimpObject):
    _attrs = ('archive_url', 'create_time', 'emails_sent', 'folder_id',
              'from_email', 'from_name', 'id', 'inline_css', 'list_id',
              'send_time', 'status', 'subject', 'title', 'to_email', 'type', 
              'web_id')
    
    _methods =  ('delete', 'pause', 'replicate', 'resume', 'schedule',
                 'send_now', 'send_test', 'unschedule')

    def __init__(self, master, info):
        super(Campaign, self).__init__(master, info)
        self.list = self.master.get_list_by_id(self.list_id)
        self._content = None
        self.frozen_info = info
        
    def __unicode__(self):
        return self.subject
    __str__ = __unicode__
    
    @property
    def content(self):
        return self.get_content()

    def get_content(self):
        if self._content is None:
            self._content = self.master.con.campaign_content(self.id)
        return self._content
    
    def send_now_async(self):
        now = datetime.datetime.utcnow()
        soon = now + datetime.timedelta(minutes=1)
        return self.schedule(soon)

    def delete(self):
        return self.master.con.campaign_delete(self.id)
        
    def pause(self):
        return self.master.con.campaign_pause(self.id)
        
    def update(self):
        status = []
        for key, value in self._get_diff():
            status.append(self.master.con.campaign_update(self.id, key, value))
        return all(status)
    
    def _get_diff(self):
        diff = []
        new_frozen = {}
        for key in self._attrs:
            current = getattr(self, key)
            if self.frozen_info[key] != current:
                diff.append((key, current))
            new_frozen[key] = current
        self.frozen_info = new_frozen
        return diff
    
    @property
    def is_sent(self):
        return self.status == 'sent'
        
        
class Member(BaseChimpObject):
    _attrs = ('email', 'timestamp')
    
    _extended_attrs = ('id', 'ip_opt', 'ip_signup', 'merges', 'status')
    
    def __init__(self, master, info):
        super(Member, self).__init__(master, info)
        
    def __unicode__(self):
        return self.email
    __str__ = __unicode__

    def __getattr__(self, attr):
        if attr in self._extended_attrs:
            return self.info[attr]
        raise AttributeError, attr
    
    @property
    def info(self):
        return self.get_info()
            
    def get_info(self):
        return self.master.master.cache.get(
            'list_member_info_%s_%s' % (self.master.id, self.email),
            self.master.master.con.list_member_info, self.master.id, self.email
        )
    
    def update(self):
        return self.master.master.con.list_update_member(self.master.id, self.email, self.merges)
        
        
class List(BaseChimpObject):
    _methods = ('batch_subscribe', 'batch_unsubscribe', 'subscribe', 
                'unsubscribe')
    
    _attrs = ('id', 'member_count', 'date_created', 'name', 'web_id')
    
    def segment_test(self, match, conditions):
        return self.master.con.campaign_segment_test(self.id, {'match': match, 'conditions': options})
    
    def add_interest_group(self, groupname):
        return self.master.con.list_interest_group_add(self.id, groupname)
        
    def remove_interest_group(self, groupname):
        return self.master.con.list_interest_group_del(self.id, groupname)
        
    def update_interest_group(self, oldname, newname):
        return self.master.con.list_interest_group_update(self.id, oldname, newname)
    
    def add_interests_if_not_exist(self, *interests):
        self.master.cache.flush('interest_groups_%s' % self.id)
        interest_groups = self.interest_groups['groups']
        for interest in set(interests):
            if interest not in interest_groups:
                self.add_interest_group(interest)
                interest_groups.append(interest)
    
    @property
    def interest_groups(self):
        return self.get_interest_groups()
    
    def get_interest_groups(self):
        return self.master.cache.get('interest_groups_%s' % self.id, self.master.con.list_interest_groups, self.id)
    
    def add_merge(self, key, desc, req={}):
        return self.master.con.list_merge_var_add(self.id, key, desc, req if req else False)
        
    def remove_merge(self, key):
        return self.master.con.list_merge_var_del(self.id, key)
    
    @property
    def merges(self):
        return self.get_merges()
    
    def get_merges(self):
        return self.master.cache.get('merges_%s' % self.id, self.master.con.list_merge_vars, self.id)
    
    def __unicode__(self):
        return self.name
    __str__ = __unicode__
    
    @property
    def members(self):
        return self.get_members()
    
    def get_members(self):
        return self.master.cache.get('members_%s' % self.id, self._get_members)
    
    def _get_members(self):
        return build_dict(self, Member, self.master.con.list_members(self.id), 'email')
    
    
class Template(BaseChimpObject):
    _attrs = ('id', 'layout', 'name', 'preview_image', 'sections')
    
    def build(self, **kwargs):
        class BuiltTemplate(object):
            def __init__(self, template, data):
                self.template = template
                self.data = data
                self.id = self.template.id
            
            def __iter__(self):
                return iter(self.data.items())
        data = {}
        for key, value in kwargs.items():
            if key in self.sections:
                data['html_%s' % key] = value
        return BuiltTemplate(self, data)


class Connection(object):
    REGULAR = REGULAR_CAMPAIGN
    PLAINTEXT = PLAINTEXT_CAMPAIGN
    ABSPLIT = ABSPLIT_CAMPAIGN
    RSS = RSS_CAMPAIGN
    TRANS = TRANS_CAMPAIGN
    AUTO = AUTO_CAMPAIGN
    DOES_NOT_EXIST = {
        'templates': TemplateDoesNotExist,
        'campaigns': CampaignDoesNotExist,
        'lists': ListDoesNotExist,
    }
    
    def __init__(self, api_key=None, secure=False, check=True):
        self._secure = secure
        self._check = check
        self._api_key = None
        self.con = None
        self.cache = Cache()
        self.is_connected = False
        if api_key is not None:
            self.connect(api_key)
            
    def connect(self, api_key):
        self._api_key = api_key
        self.con = BaseConnection(self._api_key, self._secure)
        if self._check:
            status = self.ping()
            if status != STATUS_OK:
                raise ConnectionFailed(status)
        self.is_connected = True
        
    def ping(self):
        return self.con.ping()
        
    @property
    def campaigns(self):
        return self.get_campaigns()
    
    def get_campaigns(self):
        return self.cache.get('campaigns', self._get_categories)
    
    @property
    def lists(self):
        return self.get_lists()
    
    def get_lists(self):
        return self.cache.get('lists', self._get_lists)
    
    @property
    def templates(self):
        return self.get_templates()
    
    def get_templates(self):
        return self.cache.get('templates', self._get_templates)
    
    def _get_categories(self):
        return build_dict(self, Campaign, self.con.campaigns())
    
    def _get_lists(self):
        return build_dict(self, List, self.con.lists())
    
    def _get_templates(self):
        return build_dict(self, Template, self.con.campaign_templates())
    
    def get_list_by_id(self, id):
        return self._get_by_id('lists', id)
    
    def get_campaign_by_id(self, id):
        return self._get_by_id('campaigns', id)
            
    def get_template_by_id(self, id):
        return self._get_by_id('templates', id)
    
    def get_template_by_name(self, name):
        return self._get_by_key('templates', 'name', name)
        
    def _get_by_id(self, thing, id):
        try:
            return getattr(self, thing)[id]
        except KeyError:
            self.cache.flush(thing)
            try:
                return getattr(self, thing)[id]
            except KeyError:
                raise self.DOES_NOT_EXIST[thing](id)
            
    def _get_by_key(self, thing, name, key):
        for id, obj in getattr(self, thing).items():
            if getattr(obj, name) == key:
                return obj
        raise self.DOES_NOT_EXIST[thing]('%s=%s' % (name, key))
        
    def create_campaign(self, campaign_type, campaign_list, template, subject,
            from_email, from_name, to_email, folder_id=None,
            tracking={'opens':True, 'html_clicks': True}, title='',
            authenticate=False, analytics={}, auto_footer=False,
            generate_text=False, auto_tweet=False, segment_opts={},
            type_opts={}):
        """
        Creates a new campaign and returns it for the arguments given.
        """
        options = {}
        if title:
            options['title'] = title
        else:
            options['title'] = subject
        options['list_id'] = campaign_list.id
        options['template_id'] = template.id
        options['subject'] = subject
        options['from_email'] = from_email
        options['from_name'] = from_name
        options['to_email'] = to_email
        if folder_id:
            options['folder_id'] = folder_id
        options['tracking'] = tracking
        options['authenticate'] = bool(authenticate)
        if analytics:
            options['analytics'] = analytics
        options['auto_footer'] = bool(auto_footer)
        options['generate_text'] = bool(generate_text)
        options['auto_tweet'] = bool(auto_tweet)
        content = dict(template)
        kwargs = {}
        if segment_opts['conditions']:
            kwargs['segment_opts'] = segment_opts
        if type_opts:
            kwargs['type_opts'] = type_opts
        cid = self.con.campaign_create(campaign_type, options, content,
            **kwargs)
        camp = self.get_campaign_by_id(cid)
        camp.template_object = template
        return camp
    
    def queue(self, campaign_type, contents, list_id, template_id, subject,
        from_email, from_name, to_email, folder_id=None, tracking_opens=True,
        tracking_html_clicks=True, tracking_text_clicks=False, title=None,
        authenticate=False, google_analytics=None, auto_footer=False,
        auto_tweet=False, segment_options=False, segment_options_all=True,
        segment_options_conditions=[], type_opts={}, obj=None):
        from mailchimp.models import Queue
        kwargs = locals().copy()
        del kwargs['Queue']
        del kwargs['self']
        return Queue.objects.queue(**kwargs)