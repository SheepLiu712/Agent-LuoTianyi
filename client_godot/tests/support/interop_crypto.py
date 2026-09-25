"""Isolated access to the actual server crypto functions; no server initialization."""
import ast
import base64
import logging
from pathlib import Path
from types import SimpleNamespace

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from fastapi import HTTPException


def server_crypto():
    # account.py also imports database/provider packages. Compile its exact
    # crypto functions without executing unrelated module initialization.
    source = Path(__file__).resolve().parents[3] / "server/src/system/user_interface/account.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"generate_keys", "get_public_key_pem", "decrypt_password"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    namespace = dict(rsa=rsa, padding=padding, serialization=serialization, hashes=hashes,
                     base64=base64, HTTPException=HTTPException, logger=logging.getLogger("interop"))
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), "exec"), namespace)
    return SimpleNamespace(**namespace)
