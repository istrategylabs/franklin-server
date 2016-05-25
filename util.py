from urllib.parse import parse_qs, urlparse


def filter_headers(headers, fields):
    """ Keep only the headers listed in fields that also have a truthy value.
    """
    filtered = {}
    for field in fields:
        value = headers.get(field)
        if value:
            filtered[field] = value
    return filtered


def generate_dsn(url):
    """ Parse a 12factor-style resource URL and construct a PostgreSQL DSN.

        If the URL contains a sslca query string argument with the path of
        a certificate, sslmode will be set to verify-full and sslrootcert will
        be set to the path.
    """

    components = urlparse(url)

    params = {
        'host': components.hostname or 'localhost',
        'port': components.port or 5432,
        'dbname': components.path.strip('/'),
        'user': components.username,
        'password': components.password,
    }

    if components.query:

        qs_params = parse_qs(components.query)

        if 'sslca' in qs_params:
            params['sslmode'] = 'verify-full'
            params['sslrootcert'] = qs_params['sslca'][0]

    return ' '.join('{}={}'.format(k, v) for k, v in params.items())
