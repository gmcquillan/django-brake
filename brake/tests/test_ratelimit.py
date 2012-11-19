import unittest
from unittest import TestCase
#from mox import MoxTestBase

from django.core.cache import cache
from django.test.client import Client

from brake.decorators import ratelimit


class MockRLKeys(object):
    pass


class RateLimitError(Exception):
    pass


class RateLimitTestCase(TestCase):
    """Adds assertFailsLogin and other helper methods."""

    @classmethod
    def setUpClass(cls):
        # Class Globals
        # Add any test function names here to get them automatically
        # populated in cache.
        cls.FUNCTIONS = (
            'fake_view',
        )

        cls.PERIODS = (60, 3600, 86400)
        # Setup the keys used for the ip-specific counters.
        cls.IP_TEMPLATE = ':1:rl:func:%s:period:%d:ip:127.0.0.1'
        # Keys using this template are for form field-specific counters.
        cls.FIELD_TEMPLATE = ':1:rl:func:%s:period:%s:field:username:%s'
        # Sha1 hash of 'user' used in rate limit related tests:
        cls.USERNAME_SHA1_DIGEST = 'c27d61b98062957d37496eaa594b92e6c253edba'
        cls.KEYS = MockRLKeys()
        # Create all possible combinations of IP and user_hash memcached keys.
        for period in cls.PERIODS:
            setattr(
                cls.KEYS,
                'ratelimit_login_field_%d' % (period),
                cls.FIELD_TEMPLATE % (
                    'ratelimit_login',
                    period,
                    cls.USERNAME_SHA1_DIGEST
                )
            )
            for function in cls.FUNCTIONS:
                setattr(
                    cls.KEYS,
                    '%s_ip_%d' % (function, period),
                    cls.IP_TEMPLATE % (function, period)
                )

    def _make_rl_key(self, func_name, period, field_hash):
        """Makes a ratelimit-style memcached key."""
        return self.FIELD_TEMPLATE % (
            func_name, period, field_hash
        )

    def set_field_ratelimit_counts(self, func_name, period, field_hash, count):
        """Sets the ratelimit counters for a particular instance.

        Args:
            func_name: str, name of the function being ratelimited.
                e.g.: fake_view.
            period: int, period (in seconds).
            field_hash: str, hash of field value.
                e.g. username.

        """
        if func_name in self.FUNCTIONS and period in self.PERIODS:
            cache.set(
                self._make_rl_key(func_name, period, field_hash),
                count
            )

    def setUp(self):
        super(RateLimitTestCase, self).setUp()
        self.client = Client()
        # We want fresh cache for ratelimit testing
        cache.clear()

    def tearDown(self):
        cache.clear()
        super(RateLimitTestCase, self).tearDown()


class FakeDjangoApp(object):

    @ratelimit(field='username', method='POST', rate='5/m')
    @ratelimit(field='username', method='POST', rate='10/h')
    @ratelimit(field='username', method='POST', rate='20/d')
    def ratelimit_view(self, request):
        """View used for demonstration purposes with regard to ratelimitng."""
        was_limited = getattr(request, 'limited', False)
        if was_limited:

            return RateLimitError

        return True

    def fake_login(self, request):
        """Contrived version of a login form."""
        if request.method == 'POST':
            password = getattr(request.POST, 'password', 'fail')
            if password is 'correct':

                return True

            self.ratelimit_view(request)

        return False


class TestRatelimiting(RateLimitTestCase):

    def test_allow_some_failures(self):
        """Test to make sure that short-term thresholds ignore older ones."""
        bad_payload = {'username': 'user'}
        good_payload = {'username': 'user', 'password': 'correct'}

        self.assertFalse(self.client.post(bad_payload))
        # We haven't gone over any threshold yet, so we should be able to
        # successfully login now.
        self.assertTrue(self.client.post(good_payload))


if __name__ == '__main__':
    unittest.main()
