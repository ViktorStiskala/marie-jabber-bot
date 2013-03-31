import gevent.monkey
gevent.monkey.patch_all()

from datetime import datetime, timedelta
from xmppbot import XMPPBot
from redish.client import Client

import logging
log = logging.getLogger(__name__)


class EventBot(XMPPBot):
    REDIS_CONFIG = {
        'host': 'localhost',
        'port': 6379,
        'db': "1"
    }

    def __init__(self, jid, password, redis_config=None):
        super(EventBot, self).__init__(jid, password)
        self._listeners = []
        if redis_config is not None:
            self.REDIS_CONFIG.update(redis_config)
        self._redis = Client(**self.REDIS_CONFIG)
        self._questions = self._redis.Dict(__name__ + '__questions')

    def send_question(self, to, text, question_id, timeout=0, **kwargs):
        question = {
            'to': to,
            'text': text,
            'id': question_id,
            'expires': datetime.now() + timedelta(seconds=timeout) if timeout else None,
            'sent': datetime.now()
        }
        question.update(**kwargs)

        self._questions[to] = question

        # send question to the user
        self.send_chat_message(to, text)

    def _handle_expired_question(self, question):
        # TODO: event: expired question
        del self._questions[question['to']]

    def register_listener(self, listener):
        self._listeners.append(listener)

    def message_received(self, msg):
        # handle question answers
        if msg['type'] in ('chat', 'normal') and self._questions:
            for question_to, question in self._questions.iteritems():
                # handle expired questions
                if question['expires'] is not None and question['expires'] < datetime.now():
                    self._handle_expired_question(question)
                    continue

                if msg['from'].bare == question_to:
                    # reply with confirm_text if present
                    if 'confirm_text' in question:
                        msg.reply(question['confirm_text']).send()

                # TODO: event answer received



        super(EventBot, self).message_received(msg)


    def _run_bot(self):
        super(EventBot, self)._run_bot()

        # start listeners
        for listener in self._listeners:
            listener.xmpp = self
            listener.start_later(1)