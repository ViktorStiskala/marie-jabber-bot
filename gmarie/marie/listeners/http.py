from gevent import http, Greenlet, GreenletExit
from urlparse import parse_qsl
from marie.listeners import Listener
import simplejson

import logging
log = logging.getLogger(__name__)


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
            postdata = {}  # convert to dict
            for k, v in qs:
                postdata[k] = v
        else:
            postdata = simplejson.loads(data)

        return postdata

    def answer_received(self, data):
        answer = data.get()
        print "Received answer"
        print answer

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

        # TODO: handle postdata
        self.xmpp.send_question('viktorstiskala@abdoc.net', "test", "123")

        request.send_reply(200, "OK", "OK")

    def _run(self):
        log.info('HTTP Listener serving on %s:%d...' % (self._address, self._port))
        http.HTTPServer((self._address, self._port), self._handle_connection).serve_forever()