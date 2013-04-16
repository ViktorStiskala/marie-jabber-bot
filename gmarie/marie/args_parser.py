class BaseArgsParser(object):
    def parse_args(self, args):
        raise NotImplementedError()


class SepArgsParser(BaseArgsParser):
    """
    Returns arguments separated by specified separator
    """
    def __init__(self, separator=None):
        self._sep = separator

    def parse_args(self, args):
        return args.split(self._sep)


class DummyArgsParser(BaseArgsParser):
    """Dummy parser - returns arguments intact"""

    def parse_args(self, args):
        return args
