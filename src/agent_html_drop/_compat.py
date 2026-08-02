"""TOML parsing/dumping for agent-html-drop.

The dumper is hand-written because neither `tomllib` (3.11+) nor
`tomli` (<3.11) has a write API. The loader prefers stdlib ``tomllib``
and falls back to ``tomli``.
"""
import io
from typing import Any, Dict


# TOML basic string escapes: backslash, double-quote, control chars.
_BASIC_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


def _toml_escape_str(s: str) -> str:
    out = []
    for ch in s:
        if ch in _BASIC_ESCAPES:
            out.append(_BASIC_ESCAPES[ch])
        elif ord(ch) < 0x20:
            out.append("\\u{:04x}".format(ord(ch)))
        else:
            out.append(ch)
    return "".join(out)


def _format_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return str(v).lower()
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return '"{}"'.format(_toml_escape_str(v))
    raise TypeError("Unsupported TOML scalar type: {}".format(type(v)))


def _dump_value(buf, v: Any) -> None:
    if isinstance(v, list):
        buf.write("[{}]".format(", ".join(_format_scalar(x) for x in v)))
    else:
        buf.write(_format_scalar(v))


def _dump_section(buf, data: Dict[str, Any], prefix: str) -> None:
    scalars = {}
    arrays = []
    tables = {}
    for k, v in data.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            arrays.append((k, v))
        elif isinstance(v, dict):
            tables[k] = v
        else:
            scalars[k] = v

    for k, v in scalars.items():
        buf.write("{} = ".format(k))
        _dump_value(buf, v)
        buf.write("\n")

    for k, items in arrays:
        for item in items:
            header = "{}{}".format(prefix, k)
            buf.write("\n[[{}]]\n".format(header))
            _dump_section(buf, item, prefix="")

    for k, v in tables.items():
        table_name = "{}{}".format(prefix, k)
        if prefix:
            table_name = "{}.{}".format(prefix.rstrip("."), k)
        buf.write("\n[{}]\n".format(table_name))
        _dump_section(buf, v, prefix=table_name + ".")


def _toml_dumps(data: Dict[str, Any]) -> str:
    buf = io.StringIO()
    _dump_section(buf, data, prefix="")
    return buf.getvalue()


def _toml_dump(data: Dict[str, Any], fp) -> None:
    fp.write(_toml_dumps(data))


# Loader: prefer stdlib tomllib (3.11+), fall back to tomli.
try:
    from tomllib import loads as toml_loads
except ImportError:  # Python <3.11
    from tomli import loads as toml_loads  # type: ignore[no-redef]


toml_dump = _toml_dump