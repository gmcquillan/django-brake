from django.core.cache import cache
from django.utils import unittest

from brake.decorators import ratelimit


class MockRLKeys(object):
    pass


class RateLimitError(Exception):
    pass


class FakeRequest(object):
    """A simple request stub."""
    method = 'POST'
    META = {'REMOTE_ADDR': '127.0.0.1'}

    def __init__(self, headers=None):
        if headers:
            self.META.update(headers)


class FakeClient(object):
    """An extremely light-weight test client."""

    def post(self, view_func, data, headers=None):
        request = FakeRequest(headers)
        if callable(view_func):
            request.POST = data

            return view_func(request)

        return request


class RateLimitTestCase(unittest.TestCase):
    """Adds assertFailsLogin and other helper methods."""

    @classmethod
    def setUpClass(cls):
        # Class Globals
        # Add any test function names here to get them automatically
        # populated in cache.
        cls.FUNCTIONS = (
            'fake_login',
        )

        cls.PERIODS = (60, 3600, 86400)
        # Setup the keys used for the ip-specific counters.
        cls.IP_TEMPLATE = ':1:rl:func:%s:period:%d:ip:127.0.0.1'
        # Keys using this template are for form field-specific counters.
        cls.FIELD_TEMPLATE = ':1:rl:func:%s:period:%s:field:username:%s'
        # Sha1 hash of 'user' used in rate limit related tests:
        cls.USERNAME_SHA1_DIGEST = 'efe049ccead779e455e93893366c119d44ddd8b5'
        cls.KEYS = MockRLKeys()
        # Create all possible combinations of IP and user_hash memcached keys.
        for period in cls.PERIODS:
            setattr(
                cls.KEYS,
                'fake_login_field_%d' % (period),
                cls.FIELD_TEMPLATE % (
                    'fake_login',
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
                e.g.: fake_login.
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
        self.client = FakeClient()
        # We want fresh cache for ratelimit testing
        cache.clear()

    def tearDown(self):
        cache.clear()
        super(RateLimitTestCase, self).tearDown()


#
## Some default view mocks
###

@ratelimit(field='username', method='POST', rate='5/m')
@ratelimit(field='username', method='POST', rate='10/h')
@ratelimit(field='username', method='POST', rate='20/d')
def fake_login(request):
    """Contrived version of a login form."""
    if getattr(request, 'limited', False):

        raise RateLimitError

    if request.method == 'POST':
        password = request.POST.get('password', 'fail')
        if password is not 'correct':

            return False

    return True


class TestRateLimiting(RateLimitTestCase):

    def setUp(self):
        super(TestRateLimiting, self).setUp()
        self.good_payload = {'username': u'us\xe9r', 'password': 'correct'}
        self.bad_payload = {'username': u'us\xe9r'}

    def test_allow_some_failures(self):
        """Test to make sure that short-term thresholds ignore older ones."""

        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        # We haven't gone over any threshold yet, so we should be able to
        # successfully login now.
        good_response = self.client.post(fake_login, self.good_payload)
        self.assertTrue(good_response)

    def test_fake_keys_work(self):
        """Ensure our ability to artificially set keys is accurate."""
        cache.set(self.KEYS.fake_login_ip_60, 4)
        cache.set(self.KEYS.fake_login_field_60, 4)
        cache.set(self.KEYS.fake_login_ip_3600, 4)
        cache.set(self.KEYS.fake_login_field_3600, 4)
        cache.set(self.KEYS.fake_login_ip_86400, 4)
        cache.set(self.KEYS.fake_login_field_86400, 4)

        self.client.post(fake_login, self.good_payload)

        self.assertEqual(cache.get(self.KEYS.fake_login_ip_60), 5)
        self.assertEqual(cache.get(self.KEYS.fake_login_field_60), 5)
        self.assertEqual(cache.get(self.KEYS.fake_login_ip_3600), 5)
        self.assertEqual(cache.get(self.KEYS.fake_login_field_3600), 5)
        self.assertEqual(cache.get(self.KEYS.fake_login_ip_86400), 5)
        self.assertEqual(cache.get(self.KEYS.fake_login_field_86400), 5)

    def test_ratelimit_by_ip_one_minute(self):
        """Block requests after 1 minute limit is exceeded."""
        # Set our counter as just below the threshold for our lowest period
        # We're only setting the counter for this remote IP
        cache.set(self.KEYS.fake_login_ip_60, 4)
        # Ensure that correct logins still go through.
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        # Now this most recent login has exceeded the threshold, we should get
        # an error:
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )
        # With our configuration, even good requests will be rejected.
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.good_payload
        )

    def test_ratelimit_by_field_one_minute(self):
        """Block requests after one minute limit is exceeded for a username."""
        cache.set(self.KEYS.fake_login_field_60, 4)
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_one_hour(self):
        """Block requests after 1 hour limit is exceeded."""
        cache.set(self.KEYS.fake_login_ip_3600, 9)
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_by_field_one_hour(self):
        """Block requests after 1 hour limit is exceeded for a username."""
        cache.set(self.KEYS.fake_login_field_3600, 9)
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_one_day(self):
        """Block requests after 1 hour limit is exceeded."""
        cache.set(self.KEYS.fake_login_ip_86400, 19)
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_by_field_one_day(self):
        """Block requests after 1 hour limit is exceeded for a username."""
        cache.set(self.KEYS.fake_login_field_86400, 19)
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_smaller_periods_unaffected_by_larger_periods(self):
        """Ensure that counts above a smaller period's threshold."""
        # Here we set the cache way above the 1 minute threshold, but for the
        # hourly period.
        cache.set(self.KEYS.fake_login_ip_86400, 15)
        # We will not be limited because this doesn't put us over any threshold.
        self.assertTrue(self.client.post(fake_login, self.good_payload))

    def test_overridden_get_ip_works(self):
        """Test that our MyBrake Class defined in test_settings works as expected."""
        cache.set(self.KEYS.fake_login_ip_60, 5)
        # Should trigger a ratelimit, but only from the HTTP_TRUE_CLIENT_IP
        # REMOTE_ADDR (the default) isn't in our cache at all.
        self.assertRaises(
            RateLimitError,
            self.client.post,
            fake_login,
            self.good_payload,
            headers={
                'HTTP_TRUE_CLIENT_IP': '127.0.0.1',
                'REMOTE_ADDR': '1.2.3.4'
            }
        )
