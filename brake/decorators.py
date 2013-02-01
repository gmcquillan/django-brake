import re
from functools import wraps

from django.conf import settings
from django.http import HttpResponse

class HttpResponseTooManyRequests(HttpResponse):
    status_code = 429

def _method_match(request, method=None):
    if method is None:
        method = ['GET', 'POST', 'PUT', 'DELETE', 'HEAD']
    if not isinstance(method, list):
        method = [method]
    return request.method in method


_PERIODS = {
    's': 1,
    'm': 60,
    'h': 60 * 60,
    'd': 24 * 60 * 60,
}

rate_re = re.compile('([\d]+)/([\d]*)([smhd])')


def _split_rate(rate):
    count, multi, period = rate_re.match(rate).groups()
    count = int(count)
    time = _PERIODS[period.lower()]
    if multi:
        time = time * int(multi)
    return count, time


def get_class_by_path(path):
    mod = __import__('.'.join(path.split('.')[:-1]))
    components = path.split('.')
    for comp in components[1:]:
        mod = getattr(mod, comp)

    return mod

# Allows you to override the CacheBackend in your settings.py
_backend_class = getattr(
    settings,
    'RATELIMIT_CACHE_BACKEND',
    'brake.backends.cachebe.CacheBackend'
)
_backend = get_class_by_path(_backend_class)()


def ratelimit(ip=True, block=False, method=None, field=None, rate='5/m'):
    def decorator(fn):
        func_name = fn.__name__
        count, period = _split_rate(rate)

        @wraps(fn)
        def _wrapped(request, *args, **kw):
            if _method_match(request, method):
                _backend.count(func_name, request, ip, field, period)
                limits = _backend.limit(
                    func_name, request, ip, field, count, period
                )
                if limits:
                    if block:

                        return HttpResponseTooManyRequests()

                    request.limited = True
                    request.limits = limits

            return fn(request, *args, **kw)

        return _wrapped

    return decorator
