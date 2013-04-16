# Monkey-patch stdlib (have to be used before all other imports)
import gevent.monkey
gevent.monkey.patch_all()

import logging
log = logging.getLogger(__name__)

import gevent
from gevent import Greenlet, GreenletExit
from functools import wraps
from sleekxmpp import ClientXMPP
from sleekxmpp.exceptions import IqError, IqTimeout
from args_parser import SepArgsParser, DummyArgsParser


def bot_command(async=False, args_parser=SepArgsParser()):
    def _bot_command(func):
        setattr(func, '_bot_command', True)
        setattr(func, '_bot_argsparser', args_parser)
        setattr(func, '_bot_async', async)

        def _wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wraps(func)(_wrapper)
    return _bot_command


class XMPPBot(ClientXMPP, Greenlet):
    def __init__(self, jid, password, command_prefix='', chat_command_prefix='!'):
        ClientXMPP.__init__(self, jid, password)
        Greenlet.__init__(self)

        self._cmd_prefix = command_prefix
        self._chat_cmd_prefix = chat_command_prefix

        self.add_event_handler("session_start", self.session_start)
        self.add_event_handler("message", self._message_received)

        # If you wanted more functionality, here's how to register plugins:
        # self.register_plugin('xep_0030') # Service Discovery
        # self.register_plugin('xep_0199') # XMPP Ping

        # Here's how to access plugins once you've registered them:
        # self['xep_0030'].add_feature('echo_demo')

        # If you are working with an OpenFire server, you will
        # need to use a different SSL version:
        # import ssl
        # self.ssl_version = ssl.PROTOCOL_SSLv3

    def send_chat_message(self, to, text):
        return self.send_message(to, mbody=text, mtype='chat')

    def session_start(self, event):
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

    def _process_command(self, command, params, msg):
        """
        Processes command send by the user, handles async response.

        If async is set, the command is run in separated Greenlet
        """
        method = getattr(self, command)

        def _run_command(params, msg):
            output = method(params)

            # reply with return value if not None
            if output is not None:
                msg.reply(output).send()

        if method._bot_async:
            gevent.spawn(_run_command, params, msg)
        else:
            _run_command(params, msg)

    def _message_received(self, msg):
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
    def test(self, *args):
        return "Successfully run test command"

    def _run(self):
        self.connect()
        try:
            # as `threaded` is now deprecated, it could later be removed and this command should start working.
            # running main process in gevent patched thread causes problems when exiting with KeyboardInterrupt
            # and CTRL+C has to be sent twice.
            self.process(block=False, threaded=False)
        except ValueError:
            self.process(threaded=False)
