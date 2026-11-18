"""Run isolated unit/integration workers, then E2E without competing test workers."""

import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SERVER = Path(__file__).resolve().parents[2] / "server"
LAYERS = ("unit", "integration", "e2e")


def run_layer(layer: str) -> int:
    started = time.monotonic()
    report = SERVER / f"test-results-{layer}.xml"
    report.unlink(missing_ok=True)
    with (SERVER / f"test-{layer}.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                f"tests/{layer}",
                "-m",
                "not external and not real_llm",
                "--ignore=tests/e2e/external",
                "-q",
                "--tb=short",
                "--durations=30",
                f"--junitxml={report}",
            ],
            cwd=SERVER,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    print(
        f"{layer}: {time.monotonic() - started:.2f}s, exit={result.returncode}",
        flush=True,
    )
    print((SERVER / f"test-{layer}.log").read_text(encoding="utf-8"), flush=True)
    return result.returncode


def main() -> int:
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(run_layer, LAYERS[:2]))
    # Real process/network tests retain their timing checks and run without the
    # unit/integration workers contending for disk and CPU.
    results.append(run_layer("e2e"))
    combined = ET.Element("testsuites")
    for layer in LAYERS:
        root = ET.parse(SERVER / f"test-results-{layer}.xml").getroot()
        suites = list(root.iter("testsuite"))
        if not suites or sum(int(s.get("tests", 0)) for s in suites) == 0:
            raise RuntimeError(f"No tests reported for {layer}")
        combined.extend(suites)
    ET.ElementTree(combined).write(
        SERVER / "test-results.xml", encoding="utf-8", xml_declaration=True
    )
    print(f"All server test phases: {time.monotonic() - started:.2f}s", flush=True)
    return int(any(results))


if __name__ == "__main__":
    raise SystemExit(main())
