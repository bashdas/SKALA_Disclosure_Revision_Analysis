def merge_mapping(current, update):
    return {**current, **update}


def merge_warnings(current, update):
    return list(dict.fromkeys(current + update))
