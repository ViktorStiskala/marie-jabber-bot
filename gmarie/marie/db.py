from datetime import datetime
import simplejson
from simplejson.scanner import JSONDecodeError
import redis


def default_handler(obj):
    """Serialization handler with datetime addon"""
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    else:
        raise TypeError('Object of type %s with value of %s is not JSON serializable' % (type(obj), repr(obj)))


class DataStorage(object):
    _instance = None
    ANSWER_KEY = '__answers'
    MAPPING_KEY = '__question_mapping'
    CHATROOMS_KEY = '__chatrooms'

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(DataStorage, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self, host='localhost', port=6379, db=0):
        self._connection = redis.StrictRedis(host, port, db)

    def clear_database(self):
        self._connection.flushdb()

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
        """Loads and deserializes all questions from database for the specified JID"""
        data = self._connection.hgetall(jid)
        try:
            return {k: self._decode_json(v) for k, v in data.items()}
        except JSONDecodeError:
            self._connection.delete(jid)
            return {}

    def set_question(self, jid, question_id, data):
        """Adds new question to database"""
        encoded_data = simplejson.dumps(data, default=default_handler)
        self._connection.hset(jid, question_id, encoded_data)

    def delete_questions(self, jid, *question_ids):
        """Deletes saved questions identified by questions_ids"""
        self._connection.hdel(jid, *question_ids)

    def save_answer(self, jid, answer):
        """Temporary storage for answer text when the multiple question dialog is displayed"""
        self._connection.hset(name=self.ANSWER_KEY, key=jid, value=answer)

    def load_answer(self, jid):
        """Loads saved answer text"""
        return self._connection.hget(name=self.ANSWER_KEY, key=jid)

    def delete_answer(self, jid):
        """Deletes answer text"""
        self._connection.hdel(self.ANSWER_KEY, jid)

    def get_chatrooms(self):
        data = self._connection.hgetall(self.CHATROOMS_KEY)
        return {k: simplejson.loads(v) for k, v in data.items()}

    def add_chatroom(self, room, nick, password, postback_url):
        data = {
            'nickname': nick,
            'password': password,
            'url': postback_url
        }
        self._connection.hset(self.CHATROOMS_KEY, room, simplejson.dumps(data))

    def delete_chatroom(self, room):
        self._connection.hdel(self.CHATROOMS_KEY, room)

    def set_questions_mapping(self, jid, mapping):
        """
        Sets questions mapping used for multiple question dialog.

        Mapping is in the format of number: question_id.
        Example: {'1': 'test_question_id', '2': 'second_question'}
        """

        encoded_mapping = simplejson.dumps(mapping)
        self._connection.hset(self.MAPPING_KEY, jid, encoded_mapping)

    def get_question_mapping(self, jid):
        """Loads questions mapping used for multiple question dialog"""

        data = self._connection.hget(self.MAPPING_KEY, jid)
        if data is None:
            return {}
        return simplejson.loads(data)
