#!/usr/bin/env python3
"""
契约仓库的自检：schema 自校验 + fixtures 校验 + 文档内链接检查。

三件事都是**机器能做的那部分**（附录 B 自检表第 5 条）。人肉规则会累，
所以凡是形状类的断言都压到这里，不指望下一个人读文档时记得。

    python3 tools/check_contract.py          # 全部
    python3 tools/check_contract.py schema   # 只跑其中一段
    python3 tools/check_contract.py fixtures
    python3 tools/check_contract.py links

依赖：jsonschema（links 段不需要）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "a2a-streaming-contract.md"
SCHEMA_DIR = ROOT / "schema"
FIXTURES = ROOT / "fixtures"

failures: list[str] = []


def fail(msg: str) -> None:
    failures.append(msg)
    print(f"  ✗ {msg}")


def ok(msg: str) -> None:
    print(f"  ✓ {msg}")


# ── 1. schema 自校验 ─────────────────────────────────────────────────────────

def _validator_cls():
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        print("需要 jsonschema：pip install jsonschema", file=sys.stderr)
        raise SystemExit(2)
    return Draft202012Validator


def _registry():
    """把本地 schema 按文件名注册，让 $ref: \"database-id.schema.json\" 这类相对引用能解析。"""
    from referencing import Registry, Resource

    resources = []
    for path in sorted(SCHEMA_DIR.glob("*.schema.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(doc)
        resources.append((path.name, resource))
        if "$id" in doc:
            resources.append((doc["$id"], resource))
    return Registry().with_resources(resources)


def check_schemas() -> None:
    print("[1/3] schema 自校验")
    cls = _validator_cls()
    files = sorted(SCHEMA_DIR.glob("*.schema.json"))
    if not files:
        fail("schema/ 下一个 *.schema.json 都没有")
        return
    for path in files:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            fail(f"{path.name}: JSON 解析失败 —— {exc}")
            continue
        try:
            cls.check_schema(doc)
        except Exception as exc:
            fail(f"{path.name}: 不是合法的 JSON Schema —— {exc}")
            continue
        if "$id" not in doc:
            fail(f"{path.name}: 缺 $id")
        if "title" not in doc:
            fail(f"{path.name}: 缺 title")
        ok(f"{path.name}")

    # 契约里点名的枚举必须真的在 schema 里，而不是只写在正文表格里
    stage = json.loads((SCHEMA_DIR / "stage.schema.json").read_text(encoding="utf-8"))
    declared = set(stage["$defs"]["contract-declared"]["enum"])
    was = set(stage["$defs"]["emitted-2026-09-04"]["enum"])
    now = set(stage["$defs"]["emitted-2026-09-08"]["enum"])
    # v1.10：§4.5 的 normalization 缺口关闭。守两条——历史组仍是真子集（它是缺口
    # 存在过的证据，不许被"修"成九个），当前组必须等于 contract-declared。
    if not was < declared:
        fail("stage.schema.json: emitted-2026-09-04 是历史对照，必须仍是真子集")
    elif now != declared:
        fail(f"stage.schema.json: emitted-2026-09-08 必须等于 contract-declared，"
             f"差集 {sorted(declared ^ now)}")
    else:
        ok(f"stage 枚举：声明 {len(declared)} 个、当前实发 {len(now)} 个，"
           f"**相等 ⇒ §4.5 缺口已关闭**（历史对照组仍记着当初缺的 {sorted(declared - was)}）")

    db = json.loads((SCHEMA_DIR / "database-id.schema.json").read_text(encoding="utf-8"))
    current = set(db["$defs"]["current-2026-09-04"]["enum"])
    retired = set(db["$defs"]["retired-v1.6"]["enum"])
    known = set(db["$defs"]["known"]["enum"])
    # v1.6 起 database 的契约面是 pattern，不是枚举；$defs 只是断言用的具名集合。
    # 这里守两条：退役集与生效集不得相交（否则就是改名没改干净），known 必须是二者的并。
    if current & retired:
        fail(f"database-id.schema.json: current 与 retired 相交 {sorted(current & retired)}")
    elif known != current | retired:
        fail("database-id.schema.json: known 必须等于 current ∪ retired")
    else:
        ok(f"database 契约面 = pattern {db['pattern']}；当前生效 {sorted(current)}、"
           f"v1.6 退役 {sorted(retired)}（mes_db→prod_db 改名、pm_db 并入 erp_db）")
    pattern = re.compile(db["pattern"])
    for ident in sorted(known):
        if not pattern.match(ident):
            fail(f"database-id.schema.json: 已知标识符 {ident} 不匹配自己的 pattern")


# ── 2. fixtures 校验 ─────────────────────────────────────────────────────────

def check_fixtures() -> None:
    print("[2/3] fixtures 校验")
    cls = _validator_cls()
    registry = _registry()
    manifest_path = FIXTURES / "index.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    listed = {c["file"] for c in manifest["cases"]}
    on_disk = {
        str(p.relative_to(FIXTURES))
        for p in FIXTURES.rglob("*.json")
        if p.name != "index.json"
    }
    for orphan in sorted(on_disk - listed):
        fail(f"fixture 文件没进清单：{orphan}（清单分叉就是副本漂移换个地方复发）")
    for missing in sorted(listed - on_disk):
        fail(f"清单里的文件不存在：{missing}")

    seen_ids: set[str] = set()
    for case in manifest["cases"]:
        cid = case["id"]
        if cid in seen_ids:
            fail(f"用例 id 重复：{cid}")
        seen_ids.add(cid)
        for key in ("group", "file", "schema", "expect", "trust", "why"):
            if key not in case:
                fail(f"{cid}: 清单缺字段 {key}")
        path = FIXTURES / case["file"]
        schema_path = ROOT / case["schema"]
        if not path.exists() or not schema_path.exists():
            continue

        payload = json.loads(path.read_text(encoding="utf-8"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator = cls(schema, registry=registry)
        errors = sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        actually_valid = not errors

        want_valid = case["expect"] == "valid"
        if actually_valid != want_valid:
            if want_valid:
                fail(f"{cid}: 期望通过校验，实际失败 —— {errors[0].message}")
            else:
                fail(f"{cid}: 期望校验失败，实际通过了。"
                     f"反例不报错 = 这条断言其实没在保护任何东西")
        else:
            mark = "校验通过" if actually_valid else f"如期被拒（{errors[0].message[:60]}）"
            ok(f"{cid} [{case['group']}] {mark}")

    groups = {c["group"] for c in manifest["cases"]}
    for required in ("A", "B", "C", "D", "E"):
        if required not in groups:
            fail(f"CONSUMER-TESTS.md 定义了 {required} 组，清单里一个用例都没有")


# ── 3. 文档内链接检查 ────────────────────────────────────────────────────────

_SECTION_RE = re.compile(r"^#{2,4}\s+(?:附录\s*)?([0-9]+(?:\.[0-9]+)*|[A-Z])\.?\s")
# 约定：`§X` 一律指本文的小节。引用外部规范（A2A 官方文档等）写成「规范 N 节」，
# 不带 §——否则这里会把它当成本文的小节去核对，误报，而且读者也分不清在引谁。
_REF_RE = re.compile(r"§\s*([0-9]+(?:\.[0-9]+)*)")
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
_BACKTICK_PATH_RE = re.compile(r"`((?:schema|fixtures|tools)/[A-Za-z0-9_./-]+)`")


def _headings(text: str) -> set[str]:
    found = set()
    for line in text.split("\n"):
        m = _SECTION_RE.match(line)
        if m:
            found.add(m.group(1))
    return found


def check_links() -> None:
    print("[3/3] 文档内链接检查")
    docs = sorted(p for p in ROOT.rglob("*.md") if ".git" not in p.parts)
    contract_text = CONTRACT.read_text(encoding="utf-8")
    headings = _headings(contract_text)
    # §4.6.1 这类三级引用挂在 #### 标题上，标题行写的是 "4.6.1"，已被上面收进来了
    ok(f"契约小节标题 {len(headings)} 个")

    for doc in docs:
        text = doc.read_text(encoding="utf-8")
        for ref in sorted(set(_REF_RE.findall(text))):
            # §9 这类只到一级的引用，命中任何以它开头的小节即可
            if ref in headings:
                continue
            if any(h == ref or h.startswith(ref + ".") for h in headings):
                continue
            fail(f"{doc.relative_to(ROOT)}: §{ref} 指向一个不存在的小节")
        for target in sorted(set(_LINK_RE.findall(text))):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # 相对链接按**该文件自己所在目录**解析，不是按仓库根
            if not (doc.parent / target.split("#")[0]).exists():
                fail(f"{doc.relative_to(ROOT)}: 相对链接指向不存在的文件 —— {target}")
        for target in sorted(set(_BACKTICK_PATH_RE.findall(text))):
            if not (ROOT / target).exists():
                fail(f"{doc.relative_to(ROOT)}: 正文里点名的文件不存在 —— {target}")
        ok(f"{doc.relative_to(ROOT)}")


def check_version_consistency() -> None:
    """
    `fixtures/index.json` 的 `contract_version` 必须等于状态行的版本号。

    **这条是补的一个洞。** v1.10 发布时状态行改了、`contract_version` 没跟着改，
    停在 v1.9——而发现它的不是本脚本，是**下游仓库的**
    `test_contract_version_is_the_one_we_pinned`：它按 tag 拉了 v1.10 的目录，
    读出来的 `contract_version` 却是 v1.9。

    下游按 `contract_version` 判断"我拉到的是不是我钉的那一版"。它漂了，
    下游要么误判（拉到新版却以为是旧版），要么像这次一样报一条看起来像是
    自己配错了的失败。CI 里已经有一条"状态行 == 附录 A 最新行"的检查，
    漏的正是这第三处。三处必须一起对齐。
    """
    contract = (ROOT / "a2a-streaming-contract.md").read_text(encoding="utf-8")
    status_line = next(ln for ln in contract.splitlines() if ln.startswith("> 状态："))
    m = re.search(r"v\d+\.\d+", status_line)
    declared = m.group(0) if m else ""
    index_version = json.loads(
        (ROOT / "fixtures" / "index.json").read_text(encoding="utf-8")
    )["contract_version"]
    if declared != index_version:
        fail(f"版本不一致：状态行 {declared}，fixtures/index.json {index_version}")
    else:
        ok(f"版本一致：状态行与 fixtures/index.json 都是 {declared}")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "schema"):
        check_schemas()
    if which in ("all", "fixtures"):
        check_fixtures()
    if which in ("all", "links"):
        check_links()
    if which == "all":
        check_version_consistency()
    print()
    if failures:
        print(f"失败 {len(failures)} 项：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
