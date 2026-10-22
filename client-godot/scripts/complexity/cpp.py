from functools import lru_cache
import re

from . import require_version


def syntax_error(node):
    if node.type == "ERROR" or node.is_missing:
        return f"C++ syntax error at {node.start_point.row + 1}:{node.start_point.column + 1}"
    for child in node.children:
        error = syntax_error(child)
        if error:
            return error
    return None


@lru_cache(maxsize=1)
def cpp_parser():
    require_version("tree-sitter", "0.25.2")
    require_version("tree-sitter-cpp", "0.23.4")
    from tree_sitter import Language, Parser
    import tree_sitter_cpp

    return Parser(Language(tree_sitter_cpp.language()))


def lambda_spans(node):
    if node.type == "lambda_expression":
        body = node.child_by_field_name("body")
        yield node.start_byte, body.start_byte, body.end_byte
    for child in node.children:
        yield from lambda_spans(child)


def parse_cpp(source):
    normalized = re.sub(rb"\bGDE_EXPORT\b", b" " * len(b"GDE_EXPORT"), source)
    tree = cpp_parser().parse(normalized)
    if tree.root_node.has_error:
        raise ValueError(syntax_error(tree.root_node))
    return list(lambda_spans(tree.root_node))


def shader_source(source):
    qualifiers = rb"\b(?:uniform|varying|global|instance|highp|mediump|lowp|inout|out|in)\b"
    hints = rb"\buniform\s+[^;=\n]+?(?P<hint>:\s*[\w\s,().+\-]*?)(?=\s*[=;])"
    characters = bytearray(source)
    for match in re.finditer(hints, source):
        start, end = match.span("hint")
        characters[start:end] = re.sub(rb"[^\n]", b" ", characters[start:end])
    return re.sub(qualifiers, lambda match: b" " * len(match.group()), bytes(characters))


def mask_bodies(source, spans, offset=0):
    characters = bytearray(source)
    for _, opening, end in spans:
        start, stop = opening - offset, end - offset
        for index in range(start + 1, stop - 1):
            if characters[index] != 10:
                characters[index] = 32
    return bytes(characters)


def function_records(source, path, language):
    require_version("lizard", "1.24.0")
    import lizard

    virtual = str(path) + ".cpp" if language == "Shader" else str(path)
    records = []
    for function in lizard.analyze_file.analyze_source_code(virtual, source.decode("utf-8")).function_list:
        records.append({
            "path": str(path), "name": function.name, "kind": "function",
            "line": function.start_line, "end_line": function.end_line,
            "cc": function.cyclomatic_complexity, "decisions": {}, "language": language,
        })
    return records


def lambda_record(source, span, spans, path, language):
    start, opening, end = span
    nested = [child for child in spans if opening < child[0] < child[2] < end]
    body = mask_bodies(source[opening:end], nested, opening)
    records = function_records(b"void complexity_callback() " + body, path, language)
    if len(records) != 1:
        raise ValueError("C++ lambda body could not be measured independently")
    record = records[0]
    line = source.count(b"\n", 0, start) + 1
    column = len(source[source.rfind(b"\n", 0, start) + 1:start].decode("utf-8")) + 1
    record.update(name=f"<lambda@{line}:{column}>", kind="lambda", line=line,
                  end_line=source.count(b"\n", 0, end) + 1)
    return record


def analyze(text, path):
    language = "Shader" if str(path).endswith(".gdshader") else "C++"
    source = text.encode("utf-8")
    parsed_source = shader_source(source) if language == "Shader" else source
    spans = parse_cpp(parsed_source)
    records = function_records(mask_bodies(source, spans), path, language)
    records.extend(lambda_record(source, span, spans, path, language) for span in spans)
    return records
