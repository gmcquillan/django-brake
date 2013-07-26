from decorators import _backend

"""Access limits and increment counts without using a decorator."""

def get_limits(request, label, field, periods):
    limits = []
    count = 10
    for period in periods:
        limits.extend(_backend.limit(
            label,
            request,
            field=field,
            count=count,
            period=period
        ))
        count += 10

    return limits

def inc_counts(request, label, field, periods):
    for period in periods:
        _backend.count(label, request, field=field, period=period)
