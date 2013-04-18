import simplejson
import redis


class DataStorage(object):
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DataStorage, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        self._connection = redis.StrictRedis(host='localhost', port=6379, db=0)

    def get_questions(self, jid):
        pass

    def set_question(self, jid, question_id, data):
        encoded_data = simplejson.dumps(data)
        self._connection.hset(jid, question_id, encoded_data)

    def test(self):
        print "test"
        self._connection.hset('viktorstiskala@abdoc.net', 'kfdjkfjdkfjskj', 'data')
        self._connection.hset('viktorstiskala@abdoc.net', 'test2', 'data')

        print self._connection.hgetall('viktorstiskala@abdoc.net')
