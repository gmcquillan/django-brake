from brake.backends import cachebe

class MyBrake(cachebe.CacheBackend):
    def get_ip(self, request):
        return request.META.get(
            'HTTP_TRUE_CLIENT_IP',
            request.META.get('REMOTE_ADDR')
        )
