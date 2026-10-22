def unique_selections(selections):
    seen = set()
    return [
        item
        for item in selections
        if not (item["perspective_type"] in seen or seen.add(item["perspective_type"]))
    ]
