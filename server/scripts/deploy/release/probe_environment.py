"""Evaluate locked dependencies in the target interpreter; never import the application."""

import importlib.metadata
import json
import platform
import sys

from packaging.markers import Marker
from packaging.utils import canonicalize_name


def enabled(dependency, extras):
    marker = dependency.get("marker")
    return not marker or any(Marker(marker).evaluate({"extra": extra}) for extra in extras or [""])


def selected_dependencies(lock):
    packages = {canonicalize_name(package["name"]): package for package in lock["package"]}
    if len(packages) != len(lock["package"]):
        raise ValueError("Multiple versions of one package in the lock are not supported")
    todo = [("agentluo-linux-deployment", ())]
    visited = set()
    required = {}
    while todo:
        name, extras = todo.pop()
        if (name, extras) in visited:
            continue
        visited.add((name, extras))
        package = packages[name]
        if "registry" in package["source"]:
            required[name] = package["version"]
        dependencies = list(package.get("dependencies", []))
        for extra in extras:
            dependencies.extend(package.get("optional-dependencies", {}).get(extra, []))
        for dependency in dependencies:
            if enabled(dependency, extras):
                todo.append((canonicalize_name(dependency["name"]), tuple(sorted(dependency.get("extra", [])))))
    return required


def main():
    lock = json.load(sys.stdin)
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": sys.platform,
                "machine": platform.machine(),
                "packages": {
                    canonicalize_name(d.metadata["Name"]): d.version for d in importlib.metadata.distributions()
                },
                "required": selected_dependencies(lock),
            }
        )
    )


if __name__ == "__main__":
    main()
