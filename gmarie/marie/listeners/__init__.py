from gevent import Greenlet

class Listener(Greenlet):
    def __init__(self, xmpp):
        Greenlet.__init__(self)
        self.xmpp = xmpp

    def connected(self):
        """Function called after the Listener is connected to bot class and self.xmpp is initialised"""
        pass

    def _run(self):
        raise NotImplementedError("_run has to be implemented in subclass")


