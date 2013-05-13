# Monkey-patch stdlib (have to be used before all other imports)
import gevent.monkey
gevent.monkey.patch_all()

import logging
log = logging.getLogger(__name__)

import gevent
from gevent import Greenlet
from functools import wraps
from sleekxmpp import ClientXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
from args_parser import SepArgsParser


def bot_command(f=None, block=False, args_parser=SepArgsParser()):
    """
    Bot command decorator.

    Never use `f` argument directly, used only for @bot_command decorator
    If async is set, the command is run in separated Greenlet
    """
    def _decorator(func):
        setattr(func, '_bot_command', True)
        setattr(func, '_bot_argsparser', args_parser)
        setattr(func, '_bot_async', not block)

        def _wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wraps(func)(_wrapper)

    # enable decorator usage both as @bot_command and @bot_command()
    if f is not None:
        return _decorator(f)
    return _decorator


class XMPPBot(ClientXMPP, Greenlet):
    def __init__(self, jid, password, command_prefix='', chat_command_prefix='!'):
        ClientXMPP.__init__(self, jid, password)
        Greenlet.__init__(self)

        self._cmd_prefix = command_prefix
        self._chat_cmd_prefix = chat_command_prefix
        self._authorization_sent = set()  # set of jids for which the auth request was already sent in this session
        self.user_status_presence = {}  # dict of last status presence received from user

        # automatically authorize user after sending subscription request
        self.auto_authorize = True

        # register event handlers
        self.add_event_handler('session_start', self._session_start)
        self.add_event_handler('message', self._message_received)
        self.add_event_handler('changed_status', self._user_status_changed)

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
        method = getattr(self, command)

        def _run_command(params, msg):
            output = method(params)

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
        # TODO: handle messages without type argument as type 'normal' (XMPP specification)
        if msg['type'] in ('chat', 'normal', 'groupchat'):
            try:
                prefix = self._chat_cmd_prefix if msg['type'] == 'groupchat' else self._cmd_prefix

                # process only messages starting with prefix
                if msg['body'].startswith(prefix):
                    body = msg['body'][len(prefix):]  # strip command prefix
                    # get command and params by splitting using whitespace as a separator
                    command, params = body.partition(' ')[0::2]

                    method = getattr(self, command)  # raises AttributeError if method does not exist
                    if method._bot_command:  # raises AttributeError if not bot command
                        return self._process_command(command, method._bot_argsparser.parse_args(params), msg)
            except AttributeError:
                pass

    @bot_command
    def connected_users(self, *args):
        return repr(self.client_roster)

    # TODO: privileged users
    # TODO: chat room logging

    @bot_command
    def chat(self, *args):
        return "Chat method result"

    def _run(self):
        self.connect()
        try:
            # as `threaded` is now deprecated, it could later be removed and this command should start working.
            # running main process in gevent patched thread causes problems when exiting with KeyboardInterrupt
            # and CTRL+C has to be sent twice.
            self.process(block=False, threaded=False)
        except ValueError:
            self.process(threaded=False)
