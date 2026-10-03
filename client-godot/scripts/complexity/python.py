import ast

from . import count_body, unit


CALLABLES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
DIRECT = {
    ast.If: "if", ast.IfExp: "ternary", ast.For: "loop", ast.AsyncFor: "loop",
    ast.While: "loop", ast.ExceptHandler: "catch", ast.Assert: "assert",
}


def count_match(node, counts):
    for case in node.cases:
        default = isinstance(case.pattern, ast.MatchAs) and case.pattern.pattern is None
        counts["match"] += int(not default or case.guard is not None)
        counts["guard"] += int(case.guard is not None)


def visit(node, counts):
    if isinstance(node, CALLABLES):
        return
    if type(node) in DIRECT:
        counts[DIRECT[type(node)]] += 1
    count_expressions(node, counts)
    for child in ast.iter_child_nodes(node):
        visit(child, counts)


def count_expressions(node, counts):
    if isinstance(node, ast.comprehension):
        counts["loop"] += 1
        counts["if"] += len(node.ifs)
    if isinstance(node, ast.BoolOp):
        counts["boolean"] += len(node.values) - 1
    if isinstance(node, ast.Match):
        count_match(node, counts)


def function_unit(node, path, owner):
    if isinstance(node, ast.Lambda):
        name = f'{owner or "<module>"}::<lambda@{node.lineno}:{node.col_offset + 1}>'
        body = [node.body]
        kind = "lambda"
    else:
        name = f"{owner}.{node.name}" if owner else node.name
        body = node.body
        kind = "function"
    return unit(path, name, kind, node.lineno, node.end_lineno, count_body(body, visit), "Python")


def walk(node, path, owner=""):
    if isinstance(node, CALLABLES):
        record = function_unit(node, path, owner)
        yield record
        owner = record["name"]
    if isinstance(node, ast.ClassDef):
        owner = f"{owner}.{node.name}" if owner else node.name
    for child in ast.iter_child_nodes(node):
        yield from walk(child, path, owner)


def analyze(text, path):
    tree = ast.parse(text, filename=str(path))
    records = list(walk(tree, path))
    records.append(unit(path, "<script>", "script", 1, len(text.splitlines()),
                        count_body(tree.body, visit), "Python"))
    return records
