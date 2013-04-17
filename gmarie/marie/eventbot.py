from gevent import monkey
import gevent

monkey.patch_all()

import collections
import logging
log = logging.getLogger(__name__)

from datetime import datetime, timedelta
from redish import serialization
from redish.client import Client

from xmppbot import XMPPBot, bot_command


class EventBot(XMPPBot):
    """
    XMPP Bot with listeners and event support

    Available events:
    answer_received     triggered after the eventbot received answer to particular question
    question_expired    triggered when the question timeouted
    """
    REDIS_CONFIG = {
        'host': 'localhost',
        'port': 6379,
        'db': ""
    }

    def __init__(self, jid, password, redis_config=None):
        super(EventBot, self).__init__(jid, password)
        self._events = collections.defaultdict(list)

        # Redis init
        if redis_config is not None:
            self.REDIS_CONFIG.update(redis_config)
        self._redis = Client(serializer=serialization.JSON(), **self.REDIS_CONFIG)

        QUESTIONS_KEY = __name__ + "__questions"
        try:
            self._questions = self._redis[QUESTIONS_KEY]
        except KeyError:
            self._redis[QUESTIONS_KEY] = {}
            self._questions = self._redis[QUESTIONS_KEY]

        self.add_event_handler('got_offline', self._user_got_offline)

    def register_callback(self, event, callback):
        """
        Register callback according to event name.
        Intended mainly for use by listeners
        """
        self._events[event].append(callback)

    def send_question(self, to, text, question_id, timeout=0, **kwargs):
        """
        Send question to the user.

        Supported additional kwargs:
        expire_on_offline   if set to True the question expires when the user goes offline. If the user is already
                            offline, the question expires immediately.
        postback_url        used by http listener. If specified, the answer will be sent as HTTP POST to this address.
        only_if_status      takes comma separated list of statuses. If the actual user status is not specified in this
                            list then the question will be ignored.
        """
        question = {
            'to': to,
            'text': text,
            'id': question_id,
            'expires': datetime.now() + timedelta(seconds=timeout) if timeout else None,
            'sent': datetime.now()
        }
        question.update(**kwargs)

        self._questions.setdefault(to, {})[question_id] = question

        # only_if_status checking
        try:
            statuses = question['only_if_status'].split(',')
            if self.get_user_status(jid=to) not in statuses:
                return
        except KeyError:
            pass

        # send question to the user
        self.send_chat_message(to, text)

    def stop_processing(self):
        self.stop.set()

    def _trigger_event(self, event_name, data):
        for callback in self._events[event_name]:
            gevent.spawn(callback, data)  # spawn another greenlet to execute callback (do not care about result)

    def _user_got_offline(self, presence):
        # expire all questions which has `expire_on_offline` set to True
        for question_to, questions_dict in self._questions.items():
            if presence['from'].bare == question_to:
                for question_id, question in questions_dict.items():
                    try:
                        if question['expire_on_offline']:
                            self._handle_expired_question(question)
                    except KeyError:
                        pass

    def _remove_question(self, question):
        """Removes question from redis"""
        del self._questions[question['to']][question['id']]
        if not self._questions[question['to']]:
            del self._questions[question['to']]

    def _handle_expired_question(self, question):
        self._trigger_event('question_expired', question)
        self._remove_question(question)

    def _handle_multiple_questions(self, msg, questions):
        choice_table = "To which question are you answering?\n"

        def _generate_list(_questions):
            output = ""
            num = 1
            for question_id, question in _questions.items():
                output += "[%d] %s\n" % (num, question['text'])
                num += 1

            return output.rtrim('\n')

        choice_table += _generate_list(questions)
        msg.reply(choice_table).send()

    def _message_received(self, msg):
        # handle question answers
        if msg['type'] in ('chat', 'normal') and self._questions:
            for question_to, questions_dict in self._questions.items():  # do not use iteritems -> we need local copy
                if msg['from'].bare == question_to:
                    # TODO: handle more than one question (prompt)
                    if len(questions_dict) > 1:
                        return self._handle_multiple_questions(msg, questions_dict)

                    for question_id, question in questions_dict.items():
                        # handle expired questions
                        if question['expires'] is not None and question['expires'] < datetime.now():
                            self._handle_expired_question(question)
                            continue

                        # reply with confirm_text if present
                        if 'confirm_text' in question:
                            msg.reply(question['confirm_text']).send()

                        # build answer
                        answer = {
                            'type': 'answer',
                            'id': question_id,
                            'from': msg['from'].full,
                            'answered_after': datetime.now() - question['sent'],
                            'text': msg['body'],
                            'msg_thread': msg['id']
                        }

                        self._trigger_event('answer_received', (question, answer))
                        self._remove_question(question)

                        # break after first answer
                        break
        else:
            super(EventBot, self)._message_received(msg)