import inspect
from gevent import Greenlet
import requests


def do_post_requests(postback_url, data, **kwargs):
    g = Greenlet(requests.post, postback_url, data=data, **kwargs)
    g.start()


class GatherBotCommands(type):
    """Goes through all class methods and collects bot commands into cls._bot_commands"""

    def __new__(mcs, future_class_name, future_class_parents, future_class_attr):
        cls = type(future_class_name, future_class_parents, future_class_attr)
        cls._bot_commands = {}

        for name, method in inspect.getmembers(cls, predicate=inspect.ismethod):
            if hasattr(method, '_bot_command'):
                cls._bot_commands[method._bot_name] = name

        return cls