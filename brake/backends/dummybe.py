import random

from brake.backends.cachebe import CacheBackend


class DummyBackend(CacheBackend):
    """
    A dummy rate-limiting backend that disables rate-limiting,
    for testing.
    """

    def get_ip(self, request):
        return str(random.randrange(10e20))

    def limit(self, func_name, request,
              ip=True, field=None, count=5, period=None):
        """Return limit data about any keys relevant for requst."""
        return []
