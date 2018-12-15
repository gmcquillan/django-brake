import re
from functools import wraps

from django.conf import settings
from django.http import HttpResponse

class HttpResponseTooManyRequests(HttpResponse):
    status_code = getattr(settings, 'RATELIMIT_STATUS_CODE', 403)

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


def ratelimit(
    ip=True, use_request_path=False, block=False, method=None, field=None, rate='5/m', increment=None
):
    def decorator(fn):
        count, period = _split_rate(rate)

        @wraps(fn)
        def _wrapped(request, *args, **kw):
            # Allows you to override the CacheBackend in your settings.py
            _backend_class = getattr(
                settings,
                'RATELIMIT_CACHE_BACKEND',
                'brake.backends.cachebe.CacheBackend'
            )
            _backend = get_class_by_path(_backend_class)()

            if use_request_path:
                func_name = request.path
            else:
                func_name = fn.__name__
            response = None
            if _method_match(request, method):
                limits = _backend.limit(
                    func_name, request, ip, field, count, period
                )
                if limits:
                    if block:
                        response = HttpResponseTooManyRequests()
                    request.limited = True
                    request.limits = limits

            if response is None:
                # If the response isn't HttpResponseTooManyRequests already, run
                # the actual function to get the result.
                response = fn(request, *args, **kw)

            if not isinstance(response, HttpResponseTooManyRequests):
                if _method_match(request, method) and \
                    (increment is None or (callable(increment) and increment(
                        request, response
                    ))):
                    _backend.count(func_name, request, ip, field, period)

            return response

        return _wrapped

    return decorator
