from gevent import monkey
monkey.patch_all()

from datetime import timedelta
from gevent import http, Greenlet, GreenletExit
from urlparse import parse_qsl
import grequests
from marie.listeners import Listener
import simplejson
from simplejson.decoder import JSONDecodeError

import logging
log = logging.getLogger(__name__)


def http_additional_serialize(value):
    # convert timedelta to seconds
    if isinstance(value, timedelta):
        return value.total_seconds()
    return value


class HttpListener(Listener):
    def __init__(self, xmpp, port, address="0.0.0.0"):
        super(HttpListener, self).__init__(xmpp)
        self._port = port
        self._address = address

        self.xmpp.register_callback('answer_received', self.answer_received)

    def _get_postdata(self, request, headers):
        # get input data from buffer
        data = "".join(part for part in request.input_buffer)

        if headers.get('content-type') == 'application/x-www-form-urlencoded':
            qs = parse_qsl(data)
            postdata = {}
            for k, v in qs:
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

        # send answer to `postback_url`
        try:
            if question['postback_url']:
                # serialize values inside the dictionary
                postdata = {k: http_additional_serialize(v) for k, v in answer.iteritems()}
                r = grequests.post(question['postback_url'], data=postdata)
                grequests.send(r)
        except KeyError:
            pass

    def _handle_command(self, message):
        if message is None:
            return

        try:
            if message['type'] == 'message':
                self.xmpp.send_chat_message(message['to'], message['text'])
            elif message['type'] == 'question':
                additional_args = {k: v for k, v in message.iteritems() if k not in ('to', 'id', 'text')}
                self.xmpp.send_question(message['to'], message['text'], message['id'], **additional_args)
        except KeyError:
            log.info('Ignoring unrecognized message')
            pass  # silently ignore

    def _handle_connection(self, request):
        # accept only HTTP POST
        if request.typestr != 'POST':
            request.add_output_header('Allow', 'POST')
            request.add_output_header('Content-Type', 'text/html')
            return request.send_reply(405, 'Method Not Allowed', '<h1>HTTP 405 - Method not allowed</h1>')

        # convert headers to dict (throws out headers with same name)
        headers = {}
        for k, v in request.get_input_headers():
            headers[k.lower()] = v

        postdata = self._get_postdata(request, headers)

        # handle postdata
        self._handle_command(postdata)

        request.send_reply(200, "OK", "OK")

    def _run(self):
        log.info('HTTP Listener serving on %s:%d...' % (self._address, self._port))
        http.HTTPServer((self._address, self._port), self._handle_connection).serve_forever()