from urllib.parse import parse_qs, urlparse


def filter_headers(headers, fields):
    filtered = {}
    for field in fields:
        value = headers.get(field)
        if value:
            filtered[field] = value
    return filtered


def generate_dsn(url):

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
