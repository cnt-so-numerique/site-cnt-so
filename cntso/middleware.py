import base64
from django.conf import settings
from django.http import HttpResponse


class BasicAuthMiddleware:
    """
    Middleware HTTP Basic Auth pour staging.
    Activé uniquement si BASIC_AUTH_PASSWORD est défini dans les settings.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        password = getattr(settings, 'BASIC_AUTH_PASSWORD', None)
        if not password:
            return self.get_response(request)

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Basic '):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
                _, provided_password = decoded.split(':', 1)
                if provided_password == password:
                    return self.get_response(request)
            except Exception:
                pass

        response = HttpResponse('Accès restreint', status=401)
        response['WWW-Authenticate'] = 'Basic realm="CNT-SO Staging"'
        return response
