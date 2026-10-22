from functools import lru_cache
from pathlib import Path

from . import count_body, require_version, unit


CALLABLES = {"func_def", "lambda", "property_custom_setter", "property_custom_getter"}
DIRECT = {
    "if_branch": "if", "elif_branch": "if", "inline_lambda_if": "if",
    "for_stmt": "loop", "for_stmt_typed": "loop", "while_stmt": "loop",
}


@lru_cache(maxsize=1)
def get_parser():
    require_version("gdtoolkit", "4.5.0")
    import gdtoolkit.parser as reference
    from gdtoolkit.parser.gdscript_indenter import GDScriptIndenter
    from lark import Lark

    grammar = (Path(reference.__file__).parent / "gdscript.lark").read_text(encoding="utf-8")
    grammar = grammar.replace(
        "_standalone_lambda_stmt: _simple_func_stmt",
        '_standalone_lambda_stmt: _simple_func_stmt | inline_lambda_if\n'
        'inline_lambda_if: "if" expr ":" _simple_func_stmt',
    )
    return Lark(grammar, parser="lalr", start="start", postlex=GDScriptIndenter(),
                propagate_positions=True, maybe_placeholders=False, regex=True)


def count_tokens(node, counts, category, values):
    from lark import Token

    counts[category] += sum(isinstance(child, Token) and str(child) in values for child in node.children)


def wildcard(pattern):
    from lark import Tree

    if not isinstance(pattern, Tree) or len(pattern.children) != 1:
        return False
    child = pattern.children[0]
    return isinstance(child, Tree) and str(child.data) == "wildcard_pattern"


def count_match(node, counts):
    guarded = str(node.data) == "guarded_match_branch"
    counts["match"] += int(not wildcard(node.children[0]) or guarded)
    counts["guard"] += int(guarded)


def visit(node, counts):
    from lark import Tree

    if not isinstance(node, Tree) or str(node.data) in CALLABLES | {"class_def"}:
        return
    kind = str(node.data)
    if kind in DIRECT:
        counts[DIRECT[kind]] += 1
    count_expressions(node, counts, kind)
    for child in node.children:
        visit(child, counts)


def count_expressions(node, counts, kind):
    if kind in {"test_expr", "asless_test_expr"}:
        count_tokens(node, counts, "ternary", {"if"})
    if kind in {"and_test", "or_test", "asless_and_test", "asless_or_test"}:
        count_tokens(node, counts, "boolean", {"and", "or", "&&", "||"})
    if kind in {"match_branch", "guarded_match_branch"}:
        count_match(node, counts)


def callable_name(node, owner):
    kind = str(node.data)
    if kind == "func_def":
        return str(node.children[0].children[0])
    if kind == "lambda":
        return f'{owner or "<class>"}::<lambda@{node.meta.line}:{node.meta.column}>'
    return f"<{kind}@{node.meta.line}>"


def walk(node, path, owner=""):
    from lark import Tree

    if not isinstance(node, Tree):
        return
    kind = str(node.data)
    if kind in CALLABLES:
        name = callable_name(node, owner)
        yield unit(path, name, kind, node.meta.line, node.meta.end_line,
                   count_body(node.children[1:], visit), "GDScript")
        owner = name
    if kind == "class_def":
        owner = str(node.children[0])
        yield unit(path, f"{owner}::<initializer>", "initializer", node.meta.line, node.meta.end_line,
                   count_body(node.children[1:], visit), "GDScript")
    for child in node.children:
        yield from walk(child, path, owner)


def analyze(text, path):
    tree = get_parser().parse(text + "\n")
    records = list(walk(tree, path))
    records.append(unit(path, "<script>", "script", 1, len(text.splitlines()),
                        count_body(tree.children, visit), "GDScript"))
    return records
