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
from db import DataStorage


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
        self._storage = DataStorage(**self.REDIS_CONFIG)

        self.add_event_handler('got_offline', self._user_got_offline)

    def register_callback(self, event, callback):
        """
        Register callback according to event name.
        Intended mainly for use by listeners

        answer_received
        question_expired
        groupchat_message_received
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

        self._storage.set_question(jid=to, question_id=question_id, data=question)

        # only_if_status checking
        try:
            statuses = question['only_if_status'].split(',')
            if self.get_user_status(jid=to) not in statuses:
                return
        except KeyError:
            pass

        # send question to the user
        self.send_chat_message(to, text)

    def log_chatgroup(self, room, nick=None, password=None):
        pass

    def stop_processing(self):
        self.stop.set()

    def _trigger_event(self, event_name, data):
        for callback in self._events[event_name]:
            gevent.spawn(callback, data)  # spawn another greenlet to execute callback (do not care about result)

    def _user_got_offline(self, presence):
        # expire all questions which has `expire_on_offline` set to True
        jid = presence['from'].bare
        questions = self._storage.get_questions(jid)
        for question_id, question in questions.items():
            try:
                if question['expire_on_offline']:
                    self._handle_expired_question(question)
            except KeyError:
                pass

    def _remove_question(self, question):
        """Removes question from redis"""
        self._storage.delete_questions(question['to'], question['id'])

    @bot_command(name="reset_to_defaults", min_privilege='admin')
    def _flush_storage(self):
        self._storage.clear_database()
        return "Database reset, please restart bot application"

    def _handle_expired_question(self, question):
        self._trigger_event('question_expired', question)
        self._remove_question(question)

    def _handle_multiple_questions(self, jid, msg, questions):
        choice_table = "To which question are you answering?"
        answer = self._storage.load_answer(jid)

        # choices were already displayed
        if answer:
            mapping = self._storage.get_question_mapping(jid)
            try:
                question_number = msg['body']
                question_id = mapping[question_number]

                saved_answer_text = self._storage.load_answer(jid)
                self._storage.delete_answer(jid)
                msg['body'] = unicode(saved_answer_text, encoding='utf-8')

                return self._handle_answer(question_id, questions[question_id], msg)
            except (KeyError, ValueError):
                if mapping is not None:
                    choice_table = 'Wrong number received\n\n' + choice_table
        else:
            self._storage.save_answer(jid, msg['body'])

        # save question mapping
        mapping = {}
        num = 1

        for question_id in questions.keys():
            mapping[num] = question_id
            num += 1

        # save mapping to database
        self._storage.set_questions_mapping(jid, mapping)

        def _generate_list(_mapping):
            output = ""
            for number, question_id in sorted(_mapping.items()):
                output += u"\n[%d] %s [%s]" % (number, questions[question_id]['text'], question_id)

            return output

        choice_table += _generate_list(mapping)
        msg.reply(choice_table).send()

    def _handle_answer(self, question_id, question, msg):
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

    def _message_received(self, msg):
        # trigger event on received groupchat
        if msg['type'] == 'groupchat':
            self._trigger_event('groupchat_message_received', msg)

        # handle answers
        if msg['type'] in ('chat', 'normal'):
            jid = msg['from'].bare
            questions = self._storage.get_questions(jid)

            if questions:
                for question_id, question in questions.items():
                    # handle expired questions
                    if question['expires'] is not None and question['expires'] < datetime.now():
                        self._handle_expired_question(question)
                        continue

                if len(questions) > 1:
                    return self._handle_multiple_questions(jid, msg, questions)
                else:
                    # only one question present - handle answer
                    question_id, question = questions.items()[0]
                    self._handle_answer(question_id, question, msg)
        super(EventBot, self)._message_received(msg)