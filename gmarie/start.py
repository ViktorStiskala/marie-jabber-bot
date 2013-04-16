import gevent.monkey
gevent.monkey.patch_all()

import logging

import marie
from marie.listeners.http import HttpListener
from marie.eventbot import EventBot


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)-8s %(message)s')

    with marie.serve_forever() as m:
        bot = EventBot('marie@abdoc.net', 'ozXM8vkCVy3vyOmPjqRl')
        m.start(bot)

        listener = HttpListener(bot, 8088)
        m.start(listener)