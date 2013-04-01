import gevent


class GeventJoinallManager(object):
    def __init__(self):
        super(GeventJoinallManager, self).__init__()
        self._greenlets = []

    def __enter__(self):
        return self

    def start(self, worker):
        worker.start()
        self._greenlets.append(worker)

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            gevent.joinall(self._greenlets)
        except KeyboardInterrupt:
            # TODO: real kill
            gevent.killall(self._greenlets, block=True)