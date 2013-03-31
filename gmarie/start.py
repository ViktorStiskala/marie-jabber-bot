import logging
from marie.listeners.http import HttpListener
from marie import eventbot
import gevent

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(levelname)-8s %(message)s')

    listener = HttpListener(8088)

    bot = eventbot.EventBot('marie@abdoc.net', 'ozXM8vkCVy3vyOmPjqRl')
    bot.register_listener(listener)
    bot.start()

    # bot2 = eventbot.EventBot('marie.example@jabbim.cz', 'y3cPYVrYuu8iHvtwcbWX')
    # bot2.start(block=False)
    #
    # gevent.joinall([bot.worker, bot2.worker])