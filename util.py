def filter_headers(headers, fields):
    """ Keep only the headers listed in fields that also have a truthy value.
    """
    filtered = {}
    for field in fields:
        value = headers.get(field)
        if value:
            filtered[field] = value
    return filtered
