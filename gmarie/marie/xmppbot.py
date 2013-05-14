# Monkey-patch stdlib (have to be used before all other imports)
import inspect
import gevent.monkey
from marie.utils import GatherBotCommands

gevent.monkey.patch_all()

import logging
log = logging.getLogger(__name__)

import gevent
from gevent import Greenlet
from functools import wraps
from sleekxmpp import ClientXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
from args_parser import SepArgsParser


def bot_command(f=None, name=None, min_privilege='user', block=False, args_parser=SepArgsParser()):
    """
    Bot command decorator.

    name is the name of the bot command that is going to be used
    Never use `f` argument directly, used only for @bot_command decorator
    If async is set, the command is run in separated Greenlet
    """
    def _decorator(func):
        bot_name = func.__name__ if name is None else name
        setattr(func, '_bot_command', True)
        setattr(func, '_bot_argsparser', args_parser)
        setattr(func, '_bot_async', not block)
        setattr(func, '_bot_name', bot_name)
        setattr(func, '_bot_min_privilege', min_privilege)

        def _wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wraps(func)(_wrapper)

    # enable decorator usage both as @bot_command and @bot_command()
    if f is not None:
        return _decorator(f)
    return _decorator


class XMPPBot(ClientXMPP, Greenlet):
    __metaclass__ = GatherBotCommands

    def __init__(self, jid, password, command_prefix='', chat_command_prefix='!'):
        ClientXMPP.__init__(self, jid, password)
        Greenlet.__init__(self)

        self._cmd_prefix = command_prefix
        self._chat_cmd_prefix = chat_command_prefix
        self._authorization_sent = set()  # set of jids for which the auth request was already sent in this session
        self._active_nicknames = set()
        self.user_status_presence = {}  # dict of last status presence received from user

        # automatically authorize user after sending subscription request
        self.auto_authorize = True

        # register event handlers
        self.add_event_handler('session_start', self._session_start)
        self.add_event_handler('message', self._message_received)
        self.add_event_handler('changed_status', self._user_status_changed)

        #self.add_event_handler("groupchat_message", self._message_received)

    def join_chat_room(self, room, nick, password=None):
        """Join multi user chat room"""
        self._active_nicknames.add(nick)
        return self.plugin['xep_0045'].joinMUC(room=room, nick=nick, wait=True, password=password)

    def leave_chat_room(self, room, nick):
        return self.plugin['xep_0045'].leaveMUC(room, nick)

    def send_chat_message(self, to, text, authorize_user=True):
        if authorize_user:
            self._authorize_user(to)  # make sure the subscription is already established
        return self.send_message(to, mbody=text, mtype='chat')

    def get_user_status(self, jid):
        """
        Get last user status received from user.

        Doesn't issue server call
        """
        try:
            return self.user_status_presence[jid].get_type()
        except KeyError:
            pass

        return None

    def get_user_groups(self, jid):
        return self.client_roster[jid]['groups']

    def _session_start(self, event):
        self.send_presence()
        try:
            self.get_roster()
        except IqError as e:
            log.error('Error getting roster')
            log.error(e.iq['error']['condition'])
            self.disconnect()
        except IqTimeout:
            logging.error("Server did not responded in time")
            self.disconnect()

        self.register_plugin('xep_0045')  # Multi-User Chat

    def _user_status_changed(self, presence):
        self.user_status_presence[presence['from'].bare] = presence

    def _authorize_user(self, jid):
        """
        Authorize user specified by jid.

        If the authorization request was already sent, but not in actual session then the authorization request
        will be re-sent.
        """
        try:
            subscription = self.client_roster[jid]
            if subscription['subscription'] != 'both':
                # if the subscription is pending and the request wasn't sent in actual session
                # then re-send the authorization request
                if subscription['pending_out']:
                    if jid not in self._authorization_sent:  # request wasn't sent in actual session
                        self._rerequest_authorization(jid)

                        # make sure that the authorization request is not sent more than once in current session
                        self._authorization_sent.add(jid)
                else:
                    self.send_presence(pto=jid, ptype='subscribe')
        except KeyError:  # user is not present in roster
            self.send_presence(pto=jid, ptype='subscribe')

    def _rerequest_authorization(self, jid):
        """
        Re-send authorization request.
        """
        self.send_presence(pto=jid, ptype='unsubscribe')
        gevent.sleep(0.2)
        self.send_presence(pto=jid, ptype='subscribe')

    def _process_command(self, command, params, msg):
        """
        Processes command send by the user, handles async response.
        """
        method = getattr(self, self._bot_commands[command])

        # handle privileges
        if method._bot_min_privilege in ('manager', 'admin'):
            jid = msg['from'].bare
            user_groups = self.get_user_groups(jid)
            if (method._bot_min_privilege == 'admin' and 'admin' not in user_groups) or\
            (method._bot_min_privilege == 'manager' and 'admin' not in user_groups and 'manager' not in user_groups):

                log.info('Insufficient privileges for user %s and method %s' % (jid, method.__name__))
                return

        def _run_command(params, msg):
            output = None
            try:
                output = method(*params)
            except TypeError:
                msg.reply("Wrong arguments received")
                log.warning('Wrong arguments given to method %s (got %s)' % (method.__name__, params))

            # reply with return value if not None
            if output is not None:
                msg.reply(output).send()

        # spawn new Greenlet when not running in blocking mode
        if method._bot_async:
            gevent.spawn(_run_command, params, msg)
        else:
            _run_command(params, msg)

    def _message_received(self, msg):
        """
        Handles messages received from user.
        """
        if msg['type'] is None:
            msg['type'] = 'normal'

        if msg['type'] in ('chat', 'normal', 'groupchat'):
            try:
                prefix = self._chat_cmd_prefix if msg['type'] == 'groupchat' else self._cmd_prefix
                # ignore messages from self in groupchat
                if msg['type'] == 'groupchat' and msg['mucnick'] in self._active_nicknames:
                    return

                # process only messages starting with prefix
                if msg['body'].startswith(prefix):
                    body = msg['body'][len(prefix):]  # strip command prefix
                    # get command and params by splitting using whitespace as a separator
                    command, params = body.partition(' ')[0::2]

                    method = getattr(self, self._bot_commands[command])  # raises AttributeError if method does not exist
                    if method._bot_command:  # raises AttributeError if not bot command
                        return self._process_command(command, method._bot_argsparser.parse_args(params), msg)
            except (AttributeError, KeyError):
                pass

    @bot_command
    def user_status(self, *users):
        if not users:
            return "No arguments specified. Please specify at least one JID"

        output = ""
        for user in users:
            status = self.get_user_status(user)
            if status is None:
                status = 'offline'
            output += "%s: %s\n" % (user, status)

        return output.rstrip('\n')

    @bot_command
    def users_in_roster(self, *args):
        roster_dict = dict(self.client_roster)
        users_with_any_subscription = filter(lambda x: x[1]['subscription'] != 'none', roster_dict.items())
        return "\n".join(dict(users_with_any_subscription).keys())

    # TODO: privileged users
    # TODO: chat room logging

    @bot_command
    def join_room(self, room=None, nickname=None, password=None):
        if room is None:
            return "Please specify room to join"

        nickname = 'Marie' if nickname is None else nickname
        self.join_chat_room(room, nickname, password)

    def _run(self):
        self.connect()
        try:
            # as `threaded` is now deprecated, it could later be removed and this command should start working.
            # running main process in gevent patched thread causes problems when exiting with KeyboardInterrupt
            # and CTRL+C has to be sent twice.
            self.process(block=False, threaded=False)
        except ValueError:
            self.process(threaded=False)
