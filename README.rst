================
Django Brake
================

.. image:: https://secure.travis-ci.org/gmcquillan/django-brake.png?branch=master
    :target: http://travis-ci.org/gmcquillan/django-brake

Django Brake provides a decorator to rate-limit views. Limiting can be
based on IP address or a field in the request--either a GET or POST variable.

If the rate limit is exceded, either a 403 Forbidden can be sent, or the
request can be annotated with a ``limited`` attribute, allowing you to take
another action like adding a captcha to a form.

This is a fork of Django Ratelimit, to support:

- Django 1.3 and above
- Multiple buckets (e.g. separate endpoints)
- Allow for multiple time thresholds (periods) per bucket
- Analyze which functions were limited, and what their counts were.

The intention is to remain API compliant with Django Ratelimit.

Using Django Brake
==================

``from brake.decorators import ratelimit`` is the biggest thing you need to
do. The ``@ratelimit`` decorator provides several optional arguments with
sensible defaults (in *italics*).

:``ip``:
    Whether to rate-limit based on the IP. *True*
:``block``:
    Whether to block the request instead of annotating. *False*
:``method``:
    Which HTTP method(s) to rate-limit. May be a string or a list. *all*
:``field``:
    Which HTTP field(s) to use to rate-limit. May be a string or a list. *none*
:``rate``:
    The number of requests per unit time allowed. *5/m*


Examples
--------

::

    @ratelimit()
    def myview(request):
        # Will be true if the same IP makes more than 5 requests/minute.
        was_limited = getattr(request, 'limited', False)
        return HttpResponse()

    @ratelimit(block=True)
    def myview(request):
        # If the same IP makes >5 reqs/min, will return HttpResponseForbidden
        return HttpResponse()

    @ratelimit(field='username')
    def login(request):
        # If the same username OR IP is used >5 times/min, this will be True.
        # The `username` value will come from GET or POST, determined by the
        # request method.
        was_limited = getattr(request, 'limited', False)
        return HttpResponse()

    @ratelimit(method='POST')
    def login(request):
        # Only apply rate-limiting to POSTs.
        return HttpResponseRedirect()

    @ratelimit(field=['username', 'other_field'])
    def login(request):
        # Use multiple field values.
        return HttpResponse()

    @ratelimit(rate='1/m')
    @ratelimit(rate='10/h')
    @ratelimit(rate='100/d')
    def slow(request):
        # Allow 1 reqs/min, 10 per hour, and 100 per day.
        return HttpResponse()

    #
    ## Example Login Code to *only* block login failures
    ##

    @ratelimit(field='username', method='POST', rate='5/m')
    @ratelimit(field='username', method='POST', rate='10/h')
    @ratelimit(field='username', method='POST', rate='20/d')
    def ratelimit_login(request):
        """Increment cache counters, 403 if over limit."""

        was_limited = getattr(request, 'limited', False)
        if was_limited:
            request.flash['error'] = 'You have been ratelimited'
            # Log the error, etc.

            return http.HttpResponseRedirect(urlresolvers.reverse(
                'auth_login'
            ))



    def login(request):
        """Just a regular django login flow."""
        form = forms.AuthenticationForm()
        if form.method == 'POST':
            form = forms.AuthenticationForm(data=request.POST):
                if form.is_valid()
                    # Log in user and redirect to next page.

                # Login information was not correct.
                ratelimit_login(request)

    # If you're interested in which endpoints failed, and what the
    # counts were:

    @ratelimit(field='username', method='POST', rate='1/m')
    def login(request):
        # Limits is a dict that looks like this:
        # {'period': 60, 'field': 'username', 'count', 1}
        # This can give you more insight into how to deal with
        # the ratelimiting issue.
        limits =  getattr(request, 'limits', {})

        if limits:
            return http.HttpResponseRedirect(urlresolvers.reverse(
                'auth_login'
            ))


Implementation Details:
=======================

Some Required Customization
---------------------------

By default we only track the IP that we get form
request.META['HOST_ADDR']. Unless your webservers are sitting directly
on routable IPs and have no loadbalancers or upstream proxies,
this is probably not what you want!

Since this is a deployment detail, we leave this up to those who choose
to implement Django Brake. You do so with a simple bit of Inheritence
and override.

::

    # In its own module, or in your view module; however you like:

    from brake.backends import cachebe

    class MyBrake(cachebe.CacheBackend):
        def get_ip(self, request):
            return request.META.get(
                'HTTP_TRUE_CLIENT_IP',
                request.META.get('REMOTE_ADDR')
        )

    # Now in your settings.py:

    RATELIMIT_CACHE_BACKEND = 'path.to.module.MyBrake'


.. note:: RATELIMIT_CACHE_BACKEND is now a string of the path to a
    class. The class itself should be the last in the chain.



Internals
---------

These are variables which you do not need to modify directly, but are
essential to the functioning of Brake

:``function_name``:
    This is the name of the function decorated with Brake; this allows
    us to separate into different "buckets" for each view. This is
    automatically added and doesn't need to be specified.
:``period``:
    This is derrived from the rate information passed in as a string.
    It's the number of seconds for which the increment on a bucket +
    period will be valid. It sets the TTL in memcache.


The cache key structure from *one* bad login attempt from our example
above would look something like this:

::

    # The form value derived counters:
    rl:func:<function_name>:period:<60>:field:<username>:<sha1 of username>
    rl:func:<function_name>:period:<3600>:field:<username>:<sha1 of username>
    rl:func:<function_name>:period:<86400>:field:<username>:<sha1 of username>
    # The IP derived counters:
    rl:func:<function_name>:period:<60>:ip:<ip_address>
    rl:func:<function_name>:period:<3600>:ip:<ip_address>
    rl:func:<function_name>:period:<86500>:ip:<ip_address>

*All period numbers are equivilent to the TTL for that key.*

If *any* of these thresholds are passed, then the view will 403. This is
a huge improvement in terms of usablity and security of many existing
ratelimiting applications.


Testing
=======

To run the test you need to simply run:

::

    virtualenv django-brake
    cd django-brake
    . bin/activate
    python setup.py develop
    ./test.sh

There's no slick test runner since we're trying not to fully integrate
with Django. See ``brake/tests/tests.py`` for more code examples.

Acknowledgements
================

Thanks to James Socol (`jsocol`_) on Github. A vast majority of the work on
this project is his (django-ratelimit_).

Also thanks to `Simon Willison`_'s ratelimitcache_, on which Jsocol's
version of this library is largly based.

.. _jsocol: http://github.com/jsocol
.. _django-ratelimit: https://github.com/jsocol/django-ratelimit
.. _Simon Willison: http://simonwillison.net/
.. _ratelimitcache: https://github.com/simonw/ratelimitcache
