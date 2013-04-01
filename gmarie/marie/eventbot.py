import collections
import logging
log = logging.getLogger(__name__)

from gevent.event import AsyncResult
from datetime import datetime, timedelta
from redish import serialization
from redish.client import Client

from xmppbot import XMPPBot


class EventBot(XMPPBot):
    """
    XMPP Bot with listeners and event support

    Available events:
    answer_received     triggered after the eventbot received answer to particular question
    """
    REDIS_CONFIG = {
        'host': 'localhost',
        'port': 6379,
        'db': ""
    }

    def __init__(self, jid, password, redis_config=None):
        super(EventBot, self).__init__(jid, password)
        self._events = collections.defaultdict(AsyncResult)

        # Redis init
        if redis_config is not None:
            self.REDIS_CONFIG.update(redis_config)
        self._redis = Client(serializer=serialization.JSON(), **self.REDIS_CONFIG)

        QUESTIONS_KEY = __name__ + '___questions'
        try:
            self._questions = self._redis[QUESTIONS_KEY]
        except KeyError:
            self._questions = self._redis[QUESTIONS_KEY] = {}

    def register_callback(self, event, callback):
        """
        Register callback according to event name.
        Intended mainly for use by listeners
        """
        self._events[event].rawlink(callback)

    def send_question(self, to, text, question_id, timeout=0, **kwargs):
        question = {
            'to': to,
            'text': text,
            'id': question_id,
            'expires': datetime.now() + timedelta(seconds=timeout) if timeout else None,
            'sent': datetime.now()
        }
        question.update(**kwargs)

        self._questions.setdefault(to, {})[question_id] = question

        # send question to the user
        self.send_chat_message(to, text)

    def _trigger_event(self, event_name, data):
        self._events[event_name].set(data)

    def _remove_question(self, question):
        """Removes question from redis"""
        del self._questions[question['to']][question['id']]
        if not self._questions[question['to']]:
            del self._questions[question['to']]

    def _handle_expired_question(self, question):
        # TODO: event: expired question
        self._remove_question(question)

    def _message_received(self, msg):
        # handle question answers
        if msg['type'] in ('chat', 'normal') and self._questions:
            for question_to, questions_dict in self._questions.items():  # do not use iteritems -> we need local copy
                if msg['from'].bare == question_to:
                    # TODO: handle more than one question (prompt)
                    for question_id, question in questions_dict.items():
                        # handle expired questions
                        if question['expires'] is not None and question['expires'] < datetime.now():
                            self._handle_expired_question(question)
                            continue

                        # reply with confirm_text if present
                        if 'confirm_text' in question:
                            msg.reply(question['confirm_text']).send()

                        # TODO: build answer
                        answer = {
                            'from': msg['from']
                        }
                        self._trigger_event('answer_received', answer)
                        self._remove_question(question)
        else:
            super(EventBot, self)._message_received(msg)