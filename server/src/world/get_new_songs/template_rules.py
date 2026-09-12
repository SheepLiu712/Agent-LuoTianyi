"""Package-internal, immutable template rules; no runtime configuration service."""
import json
from pathlib import Path
from types import MappingProxyType

from zhconv import convert


def structure(text):
    """Shared simplified form used for every structural comparison in the package."""
    return convert(str(text), "zh-hans")


def template_name(text):
    return structure(text).strip().replace("_", " ").removeprefix("Template:").removeprefix("模板:").casefold()


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({k: _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    return value


def _load_rules():
    path = Path(__file__).resolve().parents[3] / "config/vcpedia_templates.json"
    def fail(location, reason):
        raise ValueError(f"{path}: {location}: {reason}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail("resource", str(exc))
    lists = {"known_fields", "presentation_params", "presentation_contains", "field_exclude_params",
             "role_priority"}
    if not isinstance(data, dict) or set(data) != lists | {"description", "templates", "field_aliases"}:
        fail("resource", "expected description, templates, field_aliases and field lists")
    def strings(value, location):
        if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
            fail(location, "expected list of nonempty strings")
        return value
    if not isinstance(data["description"], str):
        fail("description", "expected string")
    for key in lists:
        strings(data[key], key)
    aliases = data["field_aliases"]
    if not isinstance(aliases, dict) or not all(isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in aliases.items()):
        fail("field_aliases", "expected nonempty string map")
    normalized = {}
    for key, value in aliases.items():
        key = structure(key).casefold()
        if key in normalized and normalized[key] != value:
            fail("field_aliases", f"conflicting alias {key!r}")
        normalized[key] = value
    data["field_aliases"] = normalized
    data["known_fields"] = {structure(key).casefold(): key for key in data["known_fields"]}
    # Fixed kinds describe existing algorithms, not an executable schema/DSL.
    fields = {
        "inline": {"text_params"}, "ruby": set(), "utawari": set(),
        "multiline": set(), "break": set(), "embed": set(),
        "staff": {"group_prefix", "list_prefix", "exclude_params"},
        "songbox": {"body_params"}, "wrapper": {"body_params"},
        "tabs": {"body_prefixes", "label_prefixes"},
        "lyrics": {"original_params", "translated_params", "original_prefix", "translated_prefix"},
    }
    if not isinstance(data["templates"], list):
        fail("templates", "expected list")
    names = {}
    for index, rule in enumerate(data["templates"]):
        location = f"templates[{index}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("kind"), str) or rule["kind"] not in fields:
            fail(location, "unknown fixed kind")
        required = fields[rule["kind"]] | {"kind", "names"}
        optional = {"contains"} if rule["kind"] == "songbox" else {"skip_if"} if rule["kind"] == "inline" else set()
        if not required <= set(rule) or set(rule) - required - optional:
            fail(location, "missing or unsupported descriptor fields")
        for key in set(rule) - {"kind"}:
            if key == "skip_if":
                conditions = rule[key]
                if not isinstance(conditions, dict) or not conditions:
                    fail(f"{location}.{key}", "expected nonempty parameter map")
                for param, values in conditions.items():
                    if not isinstance(param, str) or not param.strip():
                        fail(f"{location}.{key}", "expected nonempty parameter name")
                    if not strings(values, f"{location}.{key}.{param}"):
                        fail(f"{location}.{key}.{param}", "expected nonempty value list")
            elif key.endswith("_prefix"):
                if not isinstance(rule[key], str) or not rule[key].strip():
                    fail(f"{location}.{key}", "expected nonempty prefix string")
            else:
                strings(rule[key], f"{location}.{key}")
        rule["names"] = list(dict.fromkeys(template_name(n) for n in rule["names"]))
        for name in rule["names"]:
            if not name or name in names:
                fail(location, f"conflicting template alias {name!r}")
            names[name] = index
        if not rule["names"]:
            fail(location, "names must not be empty")
    frozen = _freeze(data)
    return frozen, MappingProxyType({name: frozen["templates"][index] for name, index in names.items()})


_RULES, _BY_NAME = _load_rules()


def descriptor(name):
    exact = _BY_NAME.get(name)
    # Historical precedence: staff, then songbox substring, then other names.
    if exact and exact["kind"] == "staff":
        return exact
    for rule in _RULES["templates"]:
        if rule["kind"] == "songbox" and any(word in name for word in rule.get("contains", ())):
            return rule
    return exact or {}


def field_key(label):
    """Canonical field name: configured alias, then known field, else the label."""
    original = label.strip()
    normkey = structure(original).casefold()
    return _RULES["field_aliases"].get(normkey, _RULES["known_fields"].get(normkey, original))


def is_presentation_key(key):
    """Whether a parameter renders presentation instead of business text."""
    key = structure(key).casefold()
    return (key in _RULES["presentation_params"]
            or any(word in key for word in _RULES["presentation_contains"]))


def is_excluded_field(key):
    """Whether a parameter is a documented non-infobox field."""
    return structure(key) in _RULES["field_exclude_params"]


def role_priority():
    """Ordered role names for single-column boxes; the first hit names the field."""
    return _RULES["role_priority"]
