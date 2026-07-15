from __future__ import unicode_literals

from six.moves.urllib.parse import quote
from werkzeug.exceptions import NotFound


def install_legacy_files_fallback():
    """Route missing /files paths into the authenticated Frappe endpoint.

    Frappe's static middleware runs before normal routes. Patching its method
    here keeps the integration contained in this app and leaves Frappe's source
    untouched.
    """
    from frappe.middlewares import StaticDataMiddleware

    if getattr(StaticDataMiddleware, '_s3_legacy_files_enabled', False):
        return

    original_call = StaticDataMiddleware.__call__

    def call_with_legacy_fallback(self, environ, start_response):
        requested_path = environ.get('PATH_INFO', '')
        if requested_path.startswith('/s3/'):
            route_parts = requested_path[len('/s3/'):].split('/')
            file_id = route_parts[0]
            if file_id and len(route_parts) <= 2:
                fallback_environ = environ.copy()
                fallback_environ['PATH_INFO'] = (
                    '/api/method/frappe_s3_attachment.controller.serve_file_by_name'
                )
                fallback_environ['QUERY_STRING'] = 'file_id={}'.format(
                    quote(file_id, safe='')
                )
                return self.app(fallback_environ, start_response)

        try:
            return original_call(self, environ, start_response)
        except NotFound:
            legacy_path = requested_path
            if not legacy_path.startswith('/files/'):
                raise

            fallback_environ = environ.copy()
            fallback_environ['PATH_INFO'] = (
                '/api/method/frappe_s3_attachment.controller.serve_legacy_file'
            )
            fallback_environ['QUERY_STRING'] = 'legacy_file_url={}'.format(
                quote(legacy_path, safe='/')
            )
            return self.app(fallback_environ, start_response)

    StaticDataMiddleware.__call__ = call_with_legacy_fallback
    StaticDataMiddleware._s3_legacy_files_enabled = True
