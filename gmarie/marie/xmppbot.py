# Monkey-patch stdlib (have to be used before all other imports)
import gevent.monkey
gevent.monkey.patch_all()

import logging
log = logging.getLogger(__name__)

import gevent
from gevent import Greenlet, GreenletExit
from sleekxmpp import ClientXMPP
from sleekxmpp.exceptions import IqError, IqTimeout


class XMPPBot(ClientXMPP, Greenlet):
    def __init__(self, jid, password):
        ClientXMPP.__init__(self, jid, password)
        Greenlet.__init__(self)

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

    def _message_received(self, msg):
        # TODO: command processing
        if msg['type'] in ('chat', 'normal'):
            msg.reply("Received message: \n%(body)s" % msg).send()

    def _run(self):
        self.connect()
        self.process(block=False)
