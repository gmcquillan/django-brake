import random

from cachebe import CacheBackend


class DummyBackend(CacheBackend):
    """
    A dummy rate-limiting backend that disables rate-limiting,
    for testing.
    """

    def get_ip(self, request):
        return str(random.randrange(10e20))
