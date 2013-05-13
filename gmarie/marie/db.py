from datetime import datetime
import simplejson
from simplejson.scanner import JSONDecodeError
import redis


def default_handler(obj):
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        raise TypeError('Object of type %s with value of %s is not JSON serializable' % (type(obj), repr(obj)))


class DataStorage(object):
    _instance = None
    ANSWER_KEY = '__answers'
    MAPPING_KEY = '__question_mapping'

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DataStorage, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, host='localhost', port=6379, db=0):
        self._connection = redis.StrictRedis(host, port, db)

    def _decode_json(self, value):
        """JSON decode function with additional datetime parsing"""
        data = simplejson.loads(value)

        def decode_datetime(date_string):
            try:
                v = datetime.strptime(date_string, '%Y-%m-%dT%H:%M:%S.%f')
                return v
            except ValueError:
                return date_string

        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, basestring):
                    data[k] = decode_datetime(v)
        return data

    def get_questions(self, jid):
        data = self._connection.hgetall(jid)
        try:
            return {k: self._decode_json(v) for k, v in data.items()}
        except JSONDecodeError:
            self._connection.delete(jid)
            return {}

    def set_question(self, jid, question_id, data):
        encoded_data = simplejson.dumps(data, default=default_handler)
        self._connection.hset(jid, question_id, encoded_data)

    def delete_questions(self, jid, *question_ids):
        self._connection.hdel(jid, *question_ids)

    def save_answer(self, jid, answer):
        self._connection.hset(name=self.ANSWER_KEY, key=jid, value=answer)

    def load_answer(self, jid):
        return self._connection.hget(name=self.ANSWER_KEY, key=jid)

    def delete_answer(self, jid):
        self._connection.hdel(self.ANSWER_KEY, jid)

    def set_questions_mapping(self, jid, mapping):
        encoded_mapping = simplejson.dumps(mapping)
        self._connection.hset(self.MAPPING_KEY, jid, encoded_mapping)

    def get_question_mapping(self, jid):
        data = self._connection.hget(self.MAPPING_KEY, jid)
        if data is None:
            return {}
        return simplejson.loads(data)
