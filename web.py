import datetime
import hmac
import logging
from base64 import b64encode
from urllib.parse import quote

import aiohttp
import aiopg
from aiohttp import web
from cachetools import TTLCache
from decouple import config

from util import filter_headers, generate_dsn


#
# configuration and settings
#

AWS_KEY = config('AWS_ACCESS_KEY')
AWS_SECRET = config('AWS_SECRET_KEY')
AWS_BUCKET = config('AWS_BUCKET')

POSTGRESQL_DSN = generate_dsn(config('DATABASE_URL'))

HOST_CACHE_TTL = config('HOST_CACHE_TTL', cast=int, default=120)
HOST_CACHE_SIZE = config('HOST_CACHE_SIZE', cast=int, default=128)

PROXY_REQUEST_HEADERS = ('Cache-Control', 'If-Modified-Since', 'If-None-Match')
PROXY_RESPONSE_HEADERS = ('Content-Length', 'Last-Modified', 'ETag')

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

# set up postgres
_pg_pool = None
async def pg_pool():
    global _pg_pool
    if not _pg_pool:
        _pg_pool = await aiopg.create_pool(POSTGRESQL_DSN)
    return _pg_pool


#
# the code that does stuff
#

async def resolve_host_config(hostname):
    """ Query Franklin API by hostname for project configuration.

        Responses are cached for HOST_CACHE_TTL seconds, retaining at most
        HOST_CACHE_SIZE cache entries.
    """

    host_config = host_cache.get(hostname)

    if not host_config:

        sql = """SELECT path
                 FROM builder_build b
                 JOIN builder_deploy d ON b.id = d.build_id
                 JOIN builder_environment e ON e.id = d.environment_id
                 WHERE e.url = %s AND b.status='SUC'
                 ORDER BY d.deployed
                 DESC LIMIT 1"""

        pool = await pg_pool()
        async with pool.acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql, (hostname,))
                row = await cur.fetchone()
                host_config = dict(zip(('path',), row))
                host_cache[hostname] = host_config

    return host_config


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

    async with aiohttp.request(method, url, headers=headers) as response:
        resource = {
            'status': response.status,
            'headers': response.headers,
            'data': await response.read(),
        }

    return resource


async def request_handler(request):
    """ Handle all requests and return the response,
        either the proxied object or an appropriate error.
    """

    hostname = request.headers.get('Host')
    host_config = await resolve_host_config(hostname)

    if not host_config:
        return web.Response(text='Host not found',
                            content_type='text/plain',
                            status=404)

    resource_path = request.match_info.get('resource_path', '')
    if resource_path == '' or resource_path.endswith('/'):
        resource_path += 'index.html'
    resource_path = quote(resource_path)

    path = '{}/{}'.format(host_config['path'], resource_path.lstrip('/'))
    request_headers = filter_headers(request.headers, PROXY_REQUEST_HEADERS)
    resource = await fetch_s3(AWS_BUCKET, path, headers=request_headers)

    if resource['status'] == 304:
        return web.Response(status=304)

    if resource['status'] != 200:
        return web.Response(body=resource['data'],
                            content_type='text/html',
                            status=404)

    response_headers = filter_headers(
        resource['headers'], PROXY_RESPONSE_HEADERS)

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
