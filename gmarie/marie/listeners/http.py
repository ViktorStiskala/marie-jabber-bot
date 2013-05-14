from marie.db import DataStorage
import re
from gevent import monkey
monkey.patch_all()

from datetime import timedelta, datetime
from gevent import http, Greenlet, GreenletExit
from urlparse import parse_qsl
import grequests
from marie.listeners import Listener
import simplejson
from simplejson.decoder import JSONDecodeError

import logging
log = logging.getLogger(__name__)


class MethodNotAllowed(Exception):
    def __init__(self, allowed_methods, *args, **kwargs):
        self.allowed_methods = allowed_methods
        super(MethodNotAllowed, self).__init__(*args, **kwargs)


class BadRequestError(Exception):
    pass


def http_additional_serialize(value):
    # convert timedelta to seconds
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, datetime):
        return value.isoformat()
    return value


class HttpListener(Listener):
    def __init__(self, xmpp, port, address="0.0.0.0"):
        super(HttpListener, self).__init__(xmpp)
        self._port = port
        self._address = address
        self._storage = DataStorage()

        self.xmpp.register_callback('answer_received', self.answer_received)
        self.xmpp.register_callback('groupchat_message_received', self._handle_groupchat_message)
        self.xmpp.add_event_handler('session_start', self._xmpp_session_started)

    def _xmpp_session_started(self, event):
        # join monitored rooms
        for room, data in self._storage.get_chatrooms().items():
            password = None if not data['password'] else data['password']
            self.xmpp.join_chat_room(room, data['nickname'], password)

    def _get_postdata(self, request, headers):
        # get input data from buffer
        data = "".join(part for part in request.input_buffer)

        if headers.get('content-type') == 'application/x-www-form-urlencoded':
            qs = parse_qsl(data)
            postdata = {}
            for k, v in qs:
                if isinstance(v, basestring):
                    try:
                        v = unicode(v)
                    except UnicodeDecodeError:
                        pass
                try:  # try to decode postdata
                    postdata[k] = simplejson.loads(v)
                except JSONDecodeError:
                    postdata[k] = v
        else:
            try:
                postdata = simplejson.loads(data)
            except JSONDecodeError:
                return None

        return postdata

    def answer_received(self, data):
        question, answer = data

        log.debug('Answer received: %s' % repr(answer))

        # send answer to `postback_url`
        try:
            if question['postback_url']:
                # serialize values inside the dictionary
                postdata = {k: http_additional_serialize(v) for k, v in answer.iteritems()}
                r = grequests.post(question['postback_url'], data=postdata)
                grequests.send(r)
        except KeyError:
            pass

    def _check_allowed_method(self, request, allow):
        if request.typestr != allow.upper():
            raise MethodNotAllowed(allow.upper())

    def _handle_groupchat_message(self, msg):
        """Handles messages received from group chat"""
        chatrooms = self._storage.get_chatrooms()

        try:
            data = chatrooms[msg['mucroom']]

            # create message
            message = {
                'from': unicode(msg['mucnick']),
                'room': unicode(msg['mucroom']),
                'text': msg['body'],
                'received': datetime.now()
            }

            postdata = {k: http_additional_serialize(v) for k, v in message.iteritems()}

            # send message to postback_url
            try:
                r = grequests.post(data['url'], data=postdata)
                grequests.send(r)
            except TypeError:
                pass
        except KeyError:
            pass

    def register_room_monitoring(self, room, nick, password, postback_url):
        self._storage.add_chatroom(room, nick, password, postback_url)
        self.xmpp.join_chat_room(room, nick, password)

    def deregister_room_monitoring(self, room):
        try:
            # try to get nickname from database
            nickname = self._storage.get_chatrooms()[room]['nickname']
            self.xmpp.leave_chat_room(room, nickname)
        except KeyError:
            log.debug('Cannot left room %s' % room)
            pass
        self._storage.delete_chatroom(room)

    def _handle_command(self, data, request):
        try:
            if re.match(r'^/message/.*', request.uri):  # message
                self._check_allowed_method(request, 'POST')

                return self.xmpp.send_chat_message(data['to'], data['text'])
            elif re.match(r'^/question/.*', request.uri):  # question
                self._check_allowed_method(request, 'POST')

                additional_args = {k: v for k, v in data.iteritems() if k not in ('to', 'id', 'text')}
                return self.xmpp.send_question(data['to'], data['text'], data['id'], **additional_args)
            elif re.match(r'^/monitor_chatroom/.*', request.uri):  # monitor chatroom
                self._check_allowed_method(request, 'POST')
                password = None
                try:
                    password = data['password']
                except KeyError:
                    pass
                return self.register_room_monitoring(data['room'], data['nickname'], password, data['postback_url'])
            elif re.match(r'^/cancel_monitoring/.*', request.uri):  # cancel chatroom monitoring
                return self.deregister_room_monitoring(data['room'])
            elif re.match(r'^/cancel_all_monitoring/.*', request.uri):  # cancel all chatrooms monitoring
                for room in self._storage.get_chatrooms().keys():
                    self.deregister_room_monitoring(room)
                return
        except KeyError:
            log.info('Ignoring unrecognized message')
            raise BadRequestError("Data missing needed attributes")

        raise BadRequestError("Uncrecognized command")

    def _handle_connection(self, request):
        # convert headers to dict (throws out headers with same name)
        headers = {}
        for k, v in request.get_input_headers():
            headers[k.lower()] = v

        postdata = self._get_postdata(request, headers)

        # handle postdata
        try:
            self._handle_command(postdata, request)
        except MethodNotAllowed as e:
            request.add_output_header('Allow', e.allowed_methods)
            request.add_output_header('Content-Type', 'text/html')
            return request.send_reply(405, 'Method Not Allowed', '<h1>Error: Method not allowed</h1>')
        except BadRequestError as e:
            request.add_output_header('Content-Type', 'text/html')
            return request.send_reply(400, 'Bad Request', '<h1>Error: Bad Request</h1>\n<p>%s</p>' % str(e))

        request.send_reply(200, "OK", "OK")

    def _run(self):
        log.info('HTTP Listener serving on %s:%d...' % (self._address, self._port))
        http.HTTPServer((self._address, self._port), self._handle_connection).serve_forever()