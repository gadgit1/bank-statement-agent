"""Цикл агента: модель предлагает шаг, код проверяет и выполняет."""
import json
import time
from pathlib import Path

from .tools import Session, execute_tool, tool_schemas

SYSTEM_PROMPT = (
    "Ты помощник по банковской выписке клиента. Отвечай по-русски и коротко. "
    "Суммы и данные бери только из инструментов, не выдумывай. "
    "Если инструмент вернул ошибку, исправь аргументы, уточни у клиента или предложи оператора. "
    "Чужие счета показывать нельзя.")
ESCALATE_TEXT = "Я зацикливаюсь на одном и том же вызове, поэтому передаю вопрос оператору."
LIMIT_TEXT = "Не удалось дать ответ за разрешённое число шагов. Передаю вопрос оператору."


def _log(path, record):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_agent(user_message: str, llm, session: Session, confirm=None,
              max_steps: int = 6, journal_path="logs/trace.jsonl") -> str:
    tools = tool_schemas()
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message}]
    recent = []
    for step in range(1, max_steps + 1):
        reply = llm.chat(messages, tools)
        calls = reply.get("tool_calls") or []
        if not calls:
            return reply.get("content") or ""
        messages.append({"role": "assistant", "content": reply.get("content"),
                         "tool_calls": [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"],
                                                      "arguments": c["arguments"]}}
                                        for c in calls]})
        for c in calls:
            recent.append((c["name"], c["arguments"]))
            if recent[-3:] == [recent[-1]] * 3:      # защита от зацикливания
                return ESCALATE_TEXT
            t0 = time.monotonic()
            result = execute_tool(c["name"], c["arguments"], session, confirm)
            _log(journal_path, {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": step, "tool": c["name"],
                "args": c["arguments"],
                "duration_ms": int((time.monotonic() - t0) * 1000),
                "error": (result.get("error") or {}).get("type"),
                "cancelled": bool(result.get("cancelled"))})
            messages.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(result, ensure_ascii=False)})
    return LIMIT_TEXT
