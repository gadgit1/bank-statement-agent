"""Opt-in end-to-end evaluation against the REAL GigaChat API (not a stub)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from llm import GigaChatLLM  # noqa: E402
from loop import run_agent  # noqa: E402
from tools import Session  # noqa: E402

CASES = {
    "taxi": ("Сколько я потратил на такси в октябре 2026?", "get_spending_summary", ("600",)),
    "food": ("Сколько я потратил на еду в октябре 2026?", "get_spending_summary", ("1250",)),
    "recurring": ("Найди мои регулярные подписки и возможные дубли.", "find_recurring_payments", ("Video Service", "Music Service")),
    "greeting": ("Привет!", None, ()),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Live GigaChat evaluation on synthetic statement")
    parser.add_argument("--runs", type=int, default=1, help="повторы каждого сценария (рекомендуется 3)")
    parser.add_argument("--case", choices=["all", *CASES], default="all")
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error("--runs must be between 1 and 5")
    load_dotenv(ROOT / ".env")
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    try:
        llm = GigaChatLLM(config["model"])
    except Exception as exc:
        print(f"Cannot initialize GigaChat: {type(exc).__name__}", file=sys.stderr)
        return 2
    session = Session(config["account_id"], Path(config["statement_path"]))
    output_dir = ROOT / "logs" / "eval"
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = CASES.items() if args.case == "all" else [(args.case, CASES[args.case])]
    totals = successes = 0
    for key, (question, expected_tool, phrases) in selected:
        for run in range(1, args.runs + 1):
            totals += 1
            trace = output_dir / f"{key}_{run}.jsonl"
            trace.unlink(missing_ok=True)
            try:
                answer = run_agent(question, llm, session, journal_path=trace)
                records = [json.loads(line) for line in trace.read_text(encoding="utf-8").splitlines()] if trace.exists() else []
                actual_tools = [r["tool"] for r in records]
                tool_ok = expected_tool in actual_tools if expected_tool else not actual_tools
                normalized = answer.replace(" ", "").replace("\u00a0", "").replace("\u202f", "").lower()
                data_ok = all(phrase.replace(" ", "").lower() in normalized for phrase in phrases)
                ok = tool_ok and data_ok
                successes += int(ok)
                print(f"{'PASS' if ok else 'FAIL'} {key} run {run}: tools={actual_tools}, answer={answer[:200]}")
            except Exception as exc:
                print(f"FAIL {key} run {run}: {type(exc).__name__} (no result)")
    print(f"\nLive LLM score: {successes}/{totals} ({successes / totals:.0%})")
    print("Traces (ignored by git): logs/eval/")
    return 0 if successes == totals else 1


if __name__ == "__main__":
    raise SystemExit(main())
