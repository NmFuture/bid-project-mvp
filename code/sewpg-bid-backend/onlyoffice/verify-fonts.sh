#!/usr/bin/env bash
set -euo pipefail

contract_path="${SEWPG_FONT_CONTRACT_PATH:-/usr/local/share/sewpg/font-contract.json}"

python3 - "${contract_path}" <<'PY'
import json
import subprocess
import sys

contract_path = sys.argv[1]
with open(contract_path, encoding="utf-8") as contract_file:
    contract = json.load(contract_file)


def resolved_family(pattern: str) -> str:
    result = subprocess.run(
        ["fc-match", "-f", "%{family[0]}", pattern],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


errors: list[str] = []
for font in contract["fonts"]:
    family = font["family"]
    for style in font["styles"]:
        pattern = f"{family}:style={style}"
        actual = resolved_family(pattern)
        if actual != family:
            errors.append(f"{pattern} -> {actual or '<missing>'}")
    for alias in font.get("aliases", []):
        for style in font["styles"]:
            pattern = f"{alias}:style={style}"
            actual = resolved_family(pattern)
            if actual != family:
                errors.append(f"alias {pattern} -> {actual or '<missing>'}, expected {family}")

if errors:
    print("OnlyOffice font contract verification failed:", file=sys.stderr)
    for error in errors:
        print(f"  - {error}", file=sys.stderr)
    raise SystemExit(1)

print(f"OnlyOffice font contract verified: {contract['version']}")
PY
