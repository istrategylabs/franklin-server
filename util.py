import mimetypes
from urllib.parse import urlparse


A_YEAR = 60 * 60 * 24 * 365

CACHE_MAX_AGES = {
    'application/atom+xml': A_YEAR,
    'application/javascript': A_YEAR,
    'application/rss+xml': A_YEAR,
    'application/vnd.ms-fontobject': A_YEAR,
    'application/x-font-ttf': A_YEAR,
    'application/x-font-otf': A_YEAR,
    'application/x-font-woff': A_YEAR,
    'application/xml': A_YEAR,
    'audio/mpeg': A_YEAR,
    'audio/webm': A_YEAR,
    'image/gif': A_YEAR,
    'image/jpeg': A_YEAR,
    'image/pjpeg': A_YEAR,
    'image/png': A_YEAR,
    'image/svg+xml': A_YEAR,
    'image/x-icon': A_YEAR,
    'text/cache-manifest': A_YEAR,
    'text/css': A_YEAR,
    'text/html': 60 * 5,  # 5 minutes
    'video/mp4': A_YEAR,
    'video/webm': A_YEAR,
}

mimetypes.add_type('application/x-font-woff', '.woff2')


def filter_headers(headers, fields):
    """ Keep only the headers listed in fields that also have a truthy value.
    """
    filtered = {}
    for field in fields:
        value = headers.get(field)
        if value:
            filtered[field] = value
    return filtered


def parse_redis_url(url):
    u = urlparse(url)
    params = {
        'address': (u.hostname, u.port or 6379),
    }
    if u.password:
        params['password'] = u.password
    return params
