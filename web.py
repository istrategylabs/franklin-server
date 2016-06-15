import datetime
import hmac
import logging
import os
from base64 import b64encode
from urllib.parse import quote, urljoin

import aiofiles
import aiohttp
from aiohttp import web
from cachetools import TTLCache
from decouple import config

from util import filter_headers


__version__ = '2.0.0'


#
# configuration and settings
#

AWS_KEY = config('AWS_ACCESS_KEY')
AWS_SECRET = config('AWS_SECRET_KEY')
AWS_BUCKET = config('AWS_BUCKET')

FRANKLIN_API_URL = config('FRANKLIN_API_URL')
FRANKLIN_API_KEY = config('FRANKLIN_API_KEY')

HOST_CACHE_TTL = config('HOST_CACHE_TTL', cast=int, default=120)
HOST_CACHE_SIZE = config('HOST_CACHE_SIZE', cast=int, default=128)

PROXY_REQUEST_HEADERS = ('Cache-Control', 'If-Modified-Since', 'If-None-Match')
PROXY_RESPONSE_HEADERS = ('Content-Length', 'Last-Modified', 'ETag')
DEFAULT_RESPONSE_HEADERS = {
    'Server': 'franklin-server/{}'.format(__version__),
}

A_YEAR = 60 * 60 * 24 * 365

CACHE_MAX_AGES = {
    'application/javascript': A_YEAR,
    'audio/mpeg': A_YEAR,
    'audio/webm': A_YEAR,
    'image/gif': A_YEAR,
    'image/jpeg': A_YEAR,
    'image/pjpeg': A_YEAR,
    'image/png': A_YEAR,
    'text/css': A_YEAR,
    'text/html': 60 * 5,  # 5 minutes
    'video/mp4': A_YEAR,
    'video/webm': A_YEAR,
}


#
# set up services and other global things
#

# set up logger
logger = logging.getLogger('franklin.server')

# set up expiring host cache
host_cache = TTLCache(maxsize=HOST_CACHE_SIZE, ttl=HOST_CACHE_TTL)

# set up aiohttp client
session = aiohttp.ClientSession()


#
# the code that does stuff
#

async def resolve_host_config(hostname):
    """ Query Franklin API by hostname for project configuration.

        Responses are cached for HOST_CACHE_TTL seconds, retaining at most
        HOST_CACHE_SIZE cache entries.
    """

    if hostname not in host_cache:

        config = {}

        url = urljoin(FRANKLIN_API_URL, '/v1/domains/')
        params = {'domain': hostname}
        headers = {
            'Authorization': 'Token {}'.format(FRANKLIN_API_KEY),
            'User-Agent': 'franklin-server/{}'.format(__version__),
        }

        async with session.get(url, params=params, headers=headers) as resp:
            if resp.status == 200:
                data = await resp.json()
                config.update(data)

        host_cache[hostname] = config

    return host_cache.get(hostname)


async def generate_signature(bucket, path, amz_date, method='GET'):
    """ Generate the signature used to sign calls to S3,
        allowing for access to objects with private ACL.
    """

    params = {
        'method': method,
        'path': '/{}/{}'.format(bucket, path.lstrip('/')),
        'amz_date': amz_date,
    }

    to_sign = '{method}\n\n\n\nx-amz-date:{amz_date}\n{path}'
    to_sign = to_sign.format(**params)

    key = bytearray(AWS_SECRET, encoding='utf-8')
    msg = bytearray(to_sign, encoding='utf-8')

    signed = hmac.new(key, msg=msg, digestmod='sha1').digest()
    signature = b64encode(signed).decode('utf-8')

    return signature


async def fetch_s3(bucket, path, method='GET', headers=None, signed=True):
    """ Fetch an object from S3, signing the request if signed=True.
        Any headers passed to fetch_s3 will be included in the request to S3.

        A dict representing the object is returned that includes the HTTP
        response status code, headers, and body.
    """

    headers = headers.copy() if headers else {}

    url = 'https://s3.amazonaws.com/{}'.format(path.lstrip('/'))
    headers['Host'] = '{}.s3.amazonaws.com'.format(bucket)

    if signed:
        now = datetime.datetime.utcnow().strftime('%a, %d-%b-%Y %H:%M:%S GMT')
        signature = await generate_signature(bucket, path, now)
        headers.update({
            'Authorization': 'AWS {}:{}'.format(AWS_KEY, signature),
            'x-amz-date': now,
        })

    async with session.request(method, url, headers=headers) as response:
        resource = {
            'status': response.status,
            'headers': response.headers,
            'data': await response.read(),
        }

    return resource


async def handle_404(host_config):
    """ Try to fetch a custom 404 page from S3. If the page exists, return it
        as expected. If it does not exist, return a default 404 page instead.
        The presence or lack of a custom 404 will be saved on the host_config
        and stored until it is evicted from the cache, but the custom file
        itself is not yet cached.
    """

    try_custom_404 = host_config.get('custom_404', True)

    if try_custom_404:

        path = '{}/404.html'.format(host_config['path'])
        resource = await fetch_s3(AWS_BUCKET, path)

        has_custom_404 = resource['status'] == 200
        host_config['custom_404'] = has_custom_404

        if has_custom_404:
            return web.Response(body=resource['data'],
                                content_type='text/html',
                                headers=DEFAULT_RESPONSE_HEADERS,
                                status=404)

    # render default 404

    path = os.path.join(os.path.dirname(__file__),
                        'templates',
                        '404-file_not_found.html')
    async with aiofiles.open(path) as fp:
        content = await fp.read()

    return web.Response(text=content,
                        content_type='text/html',
                        headers=DEFAULT_RESPONSE_HEADERS,
                        status=404)


async def request_handler(request):
    """ Handle all requests and return the response,
        either the proxied object or an appropriate error.
    """

    hostname = request.headers.get('Host')
    host_config = await resolve_host_config(hostname)

    if not host_config:

        path = os.path.join(os.path.dirname(__file__),
                            'templates',
                            '404-host_not_found.html')
        async with aiofiles.open(path) as fp:
            content = await fp.read()

        return web.Response(text=content,
                            content_type='text/html',
                            headers=DEFAULT_RESPONSE_HEADERS,
                            status=404)

    resource_path = request.match_info.get('resource_path', '')
    if resource_path == '' or resource_path.endswith('/'):
        resource_path += 'index.html'
    resource_path = quote(resource_path)

    path = '{}/{}'.format(host_config['path'], resource_path.lstrip('/'))
    request_headers = filter_headers(request.headers, PROXY_REQUEST_HEADERS)
    resource = await fetch_s3(AWS_BUCKET, path, headers=request_headers)

    if resource['status'] == 304:
        return web.Response(status=304, headers=DEFAULT_RESPONSE_HEADERS)

    if resource['status'] != 200:
        resp = await handle_404(host_config)
        return resp

    response_headers = filter_headers(
        resource['headers'], PROXY_RESPONSE_HEADERS)
    response_headers.update(DEFAULT_RESPONSE_HEADERS)

    max_age = CACHE_MAX_AGES.get(resource['headers']['Content-Type'])
    response_headers['Cache-Control'] = \
        'max-age={}'.format(max_age) if max_age else 'no-cache'

    return web.Response(body=resource['data'],
                        content_type=resource['headers']['Content-Type'],
                        headers=response_headers)


#
# make the web app and set up route
#

app = web.Application()
app.router.add_route('GET', r'/{resource_path:.*?}', request_handler)
