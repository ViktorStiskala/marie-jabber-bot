from gevent import Greenlet
import requests


def do_post_requests(postback_url, data, **kwargs):
    g = Greenlet(requests.post, postback_url, data=data, **kwargs)
    g.start()