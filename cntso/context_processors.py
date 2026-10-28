def csp(request):
    """Le nonce de la Content-Security-Policy, pour les blocs `<script>` inline
    (`cntso.middleware.ContentSecurityPolicyMiddleware`)."""
    return {'csp_nonce': getattr(request, 'csp_nonce', '')}
