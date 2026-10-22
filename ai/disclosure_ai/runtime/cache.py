import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def canonical_url(url):
    if not url:
        return ""
    parts = urlsplit(url)
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True))),
            "",
        )
    )


def normalize(args):
    if not isinstance(args, dict):
        raise ValueError("INVALID_TOOL_INPUT")
    result = dict(args)
    for key in ("query", "as_of"):
        if key in result:
            if not isinstance(result[key], str):
                raise ValueError("INVALID_TOOL_INPUT")
            result[key] = " ".join(unicodedata.normalize("NFC", result[key]).split())
    if "as_of" in result and re.fullmatch(r"\d{8}", result["as_of"]):
        value = result["as_of"]
        result["as_of"] = f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    json.dumps(result, allow_nan=False)
    return result
