"""Export or verify runtime and planned OpenAPI independently, without running a server."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.contracts.api import OPERATIONS, contract_app
from app.contracts.models import ERROR_STATUS
from app.main import app


def verify_references(value, runtime, planned, seen=None):
    seen = set() if seen is None else seen
    if isinstance(value, list):
        for child in value:
            verify_references(child, runtime, planned, seen)
    elif isinstance(value, dict):
        ref = value.get("$ref")
        if ref and ref not in seen:
            seen.add(ref)
            if not ref.startswith("#/components/"):
                raise ValueError("Unresolved external schema reference.")
            left, right = runtime, planned
            for part in ref[2:].split("/"):
                key = part.replace("~1", "/").replace("~0", "~")
                left, right = left[key], right[key]
            if left != right:
                raise ValueError(f"Component schema drift: {ref}")
            verify_references(left, runtime, planned, seen)
        for child in value.values():
            verify_references(child, runtime, planned, seen)


def verify_registration(runtime, planned):
    for path, methods in runtime["paths"].items():
        if path == "/api/health":
            continue
        for method, actual in methods.items():
            target = planned["paths"].get(path, {}).get(method)
            if not target or target.get("x-implementation-status") != "implemented":
                raise ValueError(f"Runtime route is absent or still planned: {method} {path}")
            for key in ("operationId", "parameters", "requestBody", "responses", "security"):
                if actual.get(key) != target.get(key):
                    raise ValueError(f"Implemented contract drift: {method} {path} ({key})")
            verify_references(actual, runtime, planned)
    for path, methods in planned["paths"].items():
        if path == "/api/health":
            continue
        for method, target in methods.items():
            if target.get("x-implementation-status") == "implemented" and method not in runtime[
                "paths"
            ].get(path, {}):
                raise ValueError(f"Implemented contract is not mounted: {method} {path}")


def artifacts():
    planned = contract_app.openapi()
    runtime = app.openapi()
    verify_registration(runtime, planned)
    planned["info"]["x-error-code-status"] = ERROR_STATUS
    planned["info"]["x-supported-first-business"] = "motion_comic"
    planned["info"]["x-runtime-document"] = "/openapi.json"
    planned["info"]["x-purpose"] = (
        "Design target only. Unregistered preview handlers always fail closed."
    )
    planned["paths"]["/api/health"]["get"]["x-implementation-status"] = "implemented"
    files = {
        "doc/technical/openapi/runtime.openapi.json": runtime,
        "doc/technical/openapi/first-chain.openapi.json": planned,
    }
    outputs = {
        name: json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        for name, value in files.items()
    }
    rows = [
        "# 首条链路接口清单（自动生成）",
        "",
        "由`pnpm api:generate`生成，禁止手改。健康及标注implemented的操作已实现；planned仅为设计态。权限条件详见接口契约及OpenAPI的x-permission-rule。",
        "",
        "| 方法与路径 | operationId | 实现阶段／状态 | 基础动作（条件动作另检） |",
        "| --- | --- | --- | --- |",
    ]
    for operation in OPERATIONS:
        rows.append(
            f"| {operation.method} /api/v1{operation.path} | {operation.name} | {operation.stage}／{operation.implementation} | {', '.join(operation.actions) or '按会话／purpose／处理器规则'} |"
        )
    outputs["doc/technical/openapi/接口清单.generated.md"] = "\n".join(rows) + "\n"
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    drift = []
    for name, content in artifacts().items():
        path = ROOT / name
        if args.check:
            if not path.is_file() or path.read_text() != content:
                drift.append(name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
    if drift:
        print(
            "OpenAPI drift: run pnpm api:generate; changed files: " + ", ".join(drift),
            file=sys.stderr,
        )
        return 1
    print("Runtime OpenAPI and first-chain design " + ("verified." if args.check else "exported."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
