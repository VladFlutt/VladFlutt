#!/usr/bin/env python3
"""Turn a skill-scanner JSON report into a readable summary and a pass/fail gate.

The run fails only on findings at or above FAIL_SEVERITY (default CRITICAL)
that are not listed in the baseline file. Known findings that were reviewed
and accepted live in baseline.json next to this script.

Usage:
  gate.py report.json [--baseline FILE] [--summary FILE] [--fail-on SEVERITY]
  gate.py report.json --update-baseline   # accept all current findings at the gate level
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITIES = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]
ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵", "INFO": "⚪", "SAFE": "🟢"}
HERE = Path(__file__).resolve().parent


def rank(sev: str) -> int:
    sev = (sev or "INFO").upper()
    return SEVERITIES.index(sev) if sev in SEVERITIES else len(SEVERITIES)


def norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def fingerprint(skill: str, f: dict) -> str:
    """Stable key that survives line shifts: skill, rule, file and the matched text."""
    evidence = norm(f.get("snippet")) or norm(f.get("description")) or norm(f.get("title"))
    return " | ".join([skill, f.get("rule_id") or "?", f.get("file_path") or "-", evidence[:200]])


def load_findings(report: dict) -> list[dict]:
    out = []
    for r in report.get("results", []):
        skill = r.get("skill_name") or Path(r.get("skill_path", "?")).name
        for f in r.get("findings", []) or []:
            out.append({**f, "skill": skill, "severity": (f.get("severity") or "INFO").upper(),
                        "fingerprint": fingerprint(skill, f)})
    return out


def md_cell(text: str | None, limit: int = 140) -> str:
    text = norm(text)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text.replace("|", "\\|").replace("`", "'") or "—"


def location(f: dict) -> str:
    loc = f.get("file_path") or "—"
    if f.get("line_number"):
        loc += f":{f['line_number']}"
    return f"`{f['skill']}/{loc}`" if loc != "—" else f"`{f['skill']}`"


def findings_table(items: list[dict], with_fix: bool = False) -> list[str]:
    head = "| Severity | Где | Правило | Что найдено |" + (" Как исправить |" if with_fix else "")
    sep = "|---|---|---|---|" + ("---|" if with_fix else "")
    rows = [head, sep]
    for f in sorted(items, key=lambda x: (rank(x["severity"]), x["skill"], x.get("file_path") or "")):
        row = (f"| {ICON.get(f['severity'], '')} {f['severity']} | {location(f)} | `{f.get('rule_id')}` | "
               f"{md_cell(f.get('title'))}: {md_cell(f.get('snippet') or f.get('description'))} |")
        if with_fix:
            row += f" {md_cell(f.get('remediation'))} |"
        rows.append(row)
    return rows


def build_summary(report: dict, findings: list[dict], new: list[dict], accepted: list[dict],
                  stale: list[dict], fail_on: str) -> str:
    lines: list[str] = ["## 🛡️ Проверка skills (Cisco skill-scanner)", ""]
    if new:
        lines.append(f"**❌ Найдено новых замечаний уровня {fail_on} и выше: {len(new)}.** "
                     "Их нужно исправить или, если это ложное срабатывание, добавить в "
                     "`.github/skill-scan/baseline.json` с причиной.")
    else:
        lines.append(f"**✅ Новых замечаний уровня {fail_on} и выше нет.**")
    lines.append("")

    counts = {s: 0 for s in SEVERITIES}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    results = report.get("results", [])
    lines += [
        f"Проверено skills: **{len(results)}**, всего замечаний: **{len(findings)}** "
        f"(из них в baseline: {len(accepted)}).",
        "",
        "| " + " | ".join(f"{ICON[s]} {s}" for s in SEVERITIES) + " |",
        "|" + "---:|" * len(SEVERITIES),
        "| " + " | ".join(str(counts[s]) for s in SEVERITIES) + " |",
        "",
    ]

    if new:
        lines += [f"### ❌ Новые замечания ({fail_on}+)", ""] + findings_table(new, with_fix=True) + [""]

    by_skill: dict[str, list[dict]] = {}
    for f in findings:
        by_skill.setdefault(f["skill"], []).append(f)
    lines += ["### Skills", "", "| Skill | Худшее | 🔴 | 🟠 | 🟡 | 🔵 | ⚪ |", "|---|---|---:|---:|---:|---:|---:|"]
    for r in sorted(results, key=lambda r: (rank(r.get("max_severity", "SAFE")), r.get("skill_name", ""))):
        name = r.get("skill_name", "?")
        fs = by_skill.get(name, [])
        worst = (r.get("max_severity") or "SAFE").upper()
        c = [sum(1 for f in fs if f["severity"] == s) for s in SEVERITIES]
        lines.append(f"| {name} | {ICON.get(worst, '')} {worst} | " + " | ".join(str(x) or "0" for x in c) + " |")
    lines.append("")

    if accepted:
        lines += [f"<details><summary>Известные и принятые замечания из baseline ({len(accepted)})</summary>", ""]
        lines += findings_table(accepted) + ["", "</details>", ""]

    rest = [f for f in findings if f not in new and f not in accepted and rank(f["severity"]) <= rank("MEDIUM")]
    if rest:
        lines += [f"<details><summary>Остальные замечания HIGH и MEDIUM ({len(rest)}) — не блокируют</summary>", ""]
        lines += findings_table(rest) + ["", "</details>", ""]

    if stale:
        lines += [f"ℹ️ В baseline есть {len(stale)} записей, которых больше нет в отчёте. "
                  "Их можно удалить из `baseline.json`.", ""]
    lines.append("_Полный отчёт: артефакт `skill-scan-report` этого запуска._")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report")
    ap.add_argument("--baseline", default=str(HERE / "baseline.json"))
    ap.add_argument("--summary", help="file to append the markdown summary to (e.g. $GITHUB_STEP_SUMMARY)")
    ap.add_argument("--markdown", help="file to write the markdown summary to")
    ap.add_argument("--fail-on", default="CRITICAL", choices=SEVERITIES)
    ap.add_argument("--update-baseline", action="store_true")
    args = ap.parse_args()

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    findings = load_findings(report)
    gated = [f for f in findings if rank(f["severity"]) <= rank(args.fail_on)]

    base_path = Path(args.baseline)
    baseline = json.loads(base_path.read_text(encoding="utf-8")) if base_path.exists() else {"accepted": []}
    known = {e["fingerprint"]: e for e in baseline.get("accepted", [])}

    if args.update_baseline:
        entries = []
        for f in sorted(gated, key=lambda x: x["fingerprint"]):
            old = known.get(f["fingerprint"], {})
            entries.append({"fingerprint": f["fingerprint"], "severity": f["severity"],
                            "title": f.get("title"),
                            "reason": old.get("reason", "TODO: explain why this is acceptable")})
        baseline["accepted"] = list({e["fingerprint"]: e for e in entries}.values())
        base_path.write_text(json.dumps(baseline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"baseline updated: {len(baseline['accepted'])} entries -> {base_path}")
        return 0

    new = [f for f in gated if f["fingerprint"] not in known]
    accepted = [f for f in findings if f["fingerprint"] in known]
    present = {f["fingerprint"] for f in findings}
    stale = [e for fp, e in known.items() if fp not in present]

    md = build_summary(report, findings, new, accepted, stale, args.fail_on)
    if args.summary:
        with open(args.summary, "a", encoding="utf-8") as fh:
            fh.write(md)
    if args.markdown:
        Path(args.markdown).write_text(md, encoding="utf-8")
    if not args.summary and not args.markdown:
        print(md)

    for f in new:
        loc = f".claude/skills/{f['skill']}/{f.get('file_path') or ''}"
        line = f",line={f['line_number']}" if f.get("line_number") else ""
        msg = norm(f"{f.get('rule_id')}: {f.get('title')}").replace("%", "%25").replace("\n", " ")
        print(f"::error file={loc}{line},title=skill-scanner {f['severity']}::{msg}")
    print(f"findings: {len(findings)}, gated ({args.fail_on}+): {len(gated)}, new: {len(new)}, "
          f"accepted: {len(accepted)}, stale baseline entries: {len(stale)}")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
