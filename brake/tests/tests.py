import time

import unittest
from django.core.cache import cache
from django.http import HttpResponse

from brake.decorators import ratelimit


class MockRLKeys(object):
    pass


class RateLimitError(Exception):
    pass


class FakeRequest(object):
    """A simple request stub."""
    method = 'POST'
    META = {'REMOTE_ADDR': '127.0.0.1'}
    path = 'fake_login_path'

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
            'fake_login_no_exception',
            'fake_login_path'
        )

        cls.PERIODS = (60, 3600, 86400)
        # Setup the keys used for the ip-specific counters.
        cls.IP_TEMPLATE = 'rl:func:%s:period:%d:ip:127.0.0.1'
        # Keys using this template are for form field-specific counters.
        cls.FIELD_TEMPLATE = 'rl:func:%s:period:%s:field:username:%s'
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
        cls.FAKE_LOGIN_CACHE_KEYS = [
            cls.KEYS.fake_login_field_60,
            cls.KEYS.fake_login_field_3600,
            cls.KEYS.fake_login_field_86400,
            cls.KEYS.fake_login_ip_60,
            cls.KEYS.fake_login_ip_3600,
            cls.KEYS.fake_login_ip_86400,
        ]

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


@ratelimit(field='username', method='POST', rate='10/m', block=True)
def fake_login_no_exception(request):
    """Fake view allows us to examine the response code."""
    return HttpResponse()

def fake_login_use_request_path(request):
    """Used to test use_request_path=True"""
    return HttpResponse()


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
        for initial_key in self.FAKE_LOGIN_CACHE_KEYS:
            cache.set(initial_key, (4, time.time() + 120))

        self.client.post(fake_login, self.good_payload)

        for test_key in self.FAKE_LOGIN_CACHE_KEYS:
            self.assertEqual(cache.get(test_key)[0], 5)

    def test_expiration_ttl_set_correctly(self):
        """Ensure our cache TTLs are set correctly."""
        cur_time = int(time.time())
        self.client.post(fake_login, self.bad_payload)

        for key in self.FAKE_LOGIN_CACHE_KEYS:
            # We have to use the default prefix that django cache puts on keys
            # because we are reaching into the implementation of our LocMemCache
            # implementation.
            test_ttl = int(cache._expire_info.get(':1:' + key, 0))
            expected_ttl = int(key.split(':')[4]) + cur_time
            # within a second
            self.assertAlmostEqual(test_ttl, expected_ttl, delta=1)

    def test_ratelimit_by_ip_one_minute(self):
        """Block requests after 1 minute limit is exceeded."""
        # Set our counter as the threshold for our lowest period
        # We're only setting the counter for this remote IP
        cache.set(self.KEYS.fake_login_ip_60, (5, time.time() + 120))
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
        cache.set(self.KEYS.fake_login_field_60, (5, time.time() + 120))
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_one_hour(self):
        """Block requests after 1 hour limit is exceeded."""
        cache.set(self.KEYS.fake_login_ip_3600, (10, time.time() + 120))
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_by_field_one_hour(self):
        """Block requests after 1 hour limit is exceeded for a username."""
        cache.set(self.KEYS.fake_login_field_3600, (10, time.time() + 120))
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_one_day(self):
        """Block requests after 1 hour limit is exceeded."""
        cache.set(self.KEYS.fake_login_ip_86400, (20, time.time() + 120))
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_ratelimit_by_field_one_day(self):
        """Block requests after 1 hour limit is exceeded for a username."""
        cache.set(self.KEYS.fake_login_field_86400, (20, time.time() + 120))
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        self.assertRaises(
            RateLimitError, self.client.post, fake_login, self.bad_payload
        )

    def test_smaller_periods_unaffected_by_larger_periods(self):
        """Ensure that counts above a smaller period's threshold."""
        # Here we set the cache way above the 1 minute threshold, but for the
        # hourly period.
        cache.set(self.KEYS.fake_login_ip_86400, (15, time.time() + 120))
        # We will not be limited because this doesn't put us over any threshold.
        self.assertTrue(self.client.post(fake_login, self.good_payload))

    def test_overridden_get_ip_works(self):
        """Test that our MyBrake Class defined in test_settings works."""
        cache.set(self.KEYS.fake_login_ip_60, (6, time.time() + 120))
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

    def test_status_code(self):
        """Test that our custom status code is returned."""
        cache.set(self.KEYS.fake_login_no_exception_ip_60, (20, time.time() + 120))
        result = self.client.post(fake_login_no_exception, self.bad_payload)
        # The default is 403, if we see 429, then we know our setting worked.
        self.assertEqual(result.status_code, 429)

    def test_use_request_path(self):
        """Test use_request_path=True = use request.path instead of view function name in cache key"""
        cache.set(self.KEYS.fake_login_path_ip_60, (6, time.time() + 120))
        rl = ratelimit(method='POST', use_request_path=True, rate='5/m', block=True)
        result = self.client.post(rl(fake_login_use_request_path), self.bad_payload)
        self.assertEqual(result.status_code, 429)

    def test_dont_use_request_path(self):
        """Test use_request_path=False for the same view function above"""
        cache.set(self.KEYS.fake_login_path_ip_60, (6, time.time() + 120))
        rl = ratelimit(method='POST', use_request_path=False, rate='5/m', block=True)
        result = self.client.post(rl(fake_login_use_request_path), self.bad_payload)
        self.assertEqual(result.status_code, 200)

    def test_new_counters_are_created(self):
        """Makes sure that we create counters for keys/buckets.

        This is so we know that we're populating some values for every
        bucket.
        """
        # a bad post
        self.assertFalse(self.client.post(fake_login, self.bad_payload))
        # These are the cache keys that are specified by the decorator
        # for this view.
        for key in self.FAKE_LOGIN_CACHE_KEYS:
            self.assertTrue(cache.get(key)[0] > 1)

