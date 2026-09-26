"""Package-internal, immutable template rules; no runtime configuration service."""
import json
from pathlib import Path
from types import MappingProxyType

from zhconv import convert

_RULE_LISTS = ("known_fields", "presentation_params", "presentation_contains",
               "field_exclude_params", "role_priority")
_TOP_LEVEL_KEYS = frozenset(_RULE_LISTS) | {"description", "templates", "field_aliases"}

# Fixed kinds describe existing algorithms, not an executable schema/DSL.
_KIND_FIELDS = {
    "inline": {"text_params"}, "ruby": set(), "utawari": set(),
    "multiline": set(), "break": set(), "embed": set(),
    "staff": {"group_prefix", "list_prefix", "exclude_params"},
    "songbox": {"body_params"}, "wrapper": {"body_params"},
    "tabs": {"body_prefixes", "label_prefixes"},
    "lyrics": {"original_params", "translated_params", "original_prefix", "translated_prefix"},
}
_KIND_OPTIONAL = {"songbox": {"contains"}, "inline": {"skip_if"}}


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
    data = _read_document(path)
    _normalize_field_lookups(data, path)
    names = _validate_templates(data, path)
    frozen = _freeze(data)
    return frozen, MappingProxyType({name: frozen["templates"][index] for name, index in names.items()})


def _read_document(path):
    """Load the rule document and check its top-level shape: description, field
    lists, aliases and templates."""
    def fail(location, reason):
        raise ValueError(f"{path}: {location}: {reason}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail("resource", str(exc))
    if not isinstance(data, dict) or set(data) != _TOP_LEVEL_KEYS:
        fail("resource", "expected description, templates, field_aliases and field lists")
    if not isinstance(data["description"], str):
        fail("description", "expected string")
    for key in _RULE_LISTS:
        _string_list(data[key], key, fail)
    aliases = data["field_aliases"]
    if not isinstance(aliases, dict) or not all(
            isinstance(key, str) and key.strip() and isinstance(value, str) and value.strip()
            for key, value in aliases.items()):
        fail("field_aliases", "expected nonempty string map")
    return data


def _normalize_field_lookups(data, path):
    """Alias and known-field lookups compare in one normalized form."""
    def fail(location, reason):
        raise ValueError(f"{path}: {location}: {reason}")

    normalized = {}
    for key, value in data["field_aliases"].items():
        key = structure(key).casefold()
        if key in normalized and normalized[key] != value:
            fail("field_aliases", f"conflicting alias {key!r}")
        normalized[key] = value
    data["field_aliases"] = normalized
    data["known_fields"] = {structure(key).casefold(): key for key in data["known_fields"]}


def _validate_templates(data, path):
    """Check every template descriptor against its fixed kind; return the name index."""
    def fail(location, reason):
        raise ValueError(f"{path}: {location}: {reason}")

    names = {}
    for index, rule in enumerate(data["templates"]):
        location = f"templates[{index}]"
        if not isinstance(rule, dict) or not isinstance(rule.get("kind"), str) or rule["kind"] not in _KIND_FIELDS:
            fail(location, "unknown fixed kind")
        if not _descriptor_shape_ok(rule):
            fail(location, "missing or unsupported descriptor fields")
        for key in set(rule) - {"kind"}:
            _validate_descriptor_field(rule, key, f"{location}.{key}", fail)
        rule["names"] = list(dict.fromkeys(template_name(n) for n in rule["names"]))
        for name in rule["names"]:
            if not name or name in names:
                fail(location, f"conflicting template alias {name!r}")
            names[name] = index
        if not rule["names"]:
            fail(location, "names must not be empty")
    return names


def _descriptor_shape_ok(rule):
    required = _KIND_FIELDS[rule["kind"]] | {"kind", "names"}
    optional = _KIND_OPTIONAL.get(rule["kind"], set())
    return required <= set(rule) and not set(rule) - required - optional


def _validate_descriptor_field(rule, key, location, fail):
    if key == "skip_if":
        conditions = rule[key]
        if not isinstance(conditions, dict) or not conditions:
            fail(location, "expected nonempty parameter map")
        for param, values in conditions.items():
            if not isinstance(param, str) or not param.strip():
                fail(location, "expected nonempty parameter name")
            _string_list(values, f"{location}.{param}", fail)
    elif key.endswith("_prefix"):
        if not isinstance(rule[key], str) or not rule[key].strip():
            fail(location, "expected nonempty prefix string")
    else:
        _string_list(rule[key], location, fail)


def _string_list(value, location, fail):
    if not isinstance(value, list) or not all(isinstance(x, str) and x.strip() for x in value):
        fail(location, "expected list of nonempty strings")
    return value


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
