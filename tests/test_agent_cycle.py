"""Harness tests without a real model. These DO NOT replace LLM eval runs."""
import json

OCT = {"date_from": "2026-10-01", "date_to": "2026-10-31", "category": "taxi"}

class ScriptedLLM:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.messages_seen = []
    def chat(self, messages, schemas):
        self.messages_seen.append(json.loads(json.dumps(messages)))
        return next(self.replies)


def tool_reply(name, args, id="call1"):
    return {"content": None, "tool_calls": [{"id": id, "name": name, "arguments": json.dumps(args)}]}


def test_greeting_does_not_require_tools(loop, session, tmp_path):
    fake = ScriptedLLM([{"content": "Здравствуйте!", "tool_calls": []}])
    result = loop.run_agent("Привет", fake, session, journal_path=tmp_path / "trace.jsonl")
    assert result == "Здравствуйте!"
    assert len(fake.messages_seen) == 1


def test_tool_result_returns_to_model(loop, session, tmp_path):
    fake = ScriptedLLM([tool_reply("get_spending_summary", OCT), {"content": "На такси 500 ₽"}])
    p = tmp_path / "trace.jsonl"
    result = loop.run_agent("Сколько ушло на такси?", fake, session, journal_path=p)
    assert result == "На такси 500 ₽"
    seen_tool_message = fake.messages_seen[1][-1]
    assert seen_tool_message["role"] == "tool"
    assert json.loads(seen_tool_message["content"])["result"]["total_rub"] == 500
    trace = json.loads(p.read_text(encoding="utf-8").splitlines()[0])
    assert trace["tool"] == "get_spending_summary"


def test_tool_error_does_not_crash_agent(loop, session, tmp_path, tools):
    tools.FAULTS["get_spending_summary"] = ["timeout"] * 3
    fake = ScriptedLLM([tool_reply("get_spending_summary", OCT), {"content": "Сервис недоступен, суммы не буду выдумывать."}])
    result = loop.run_agent("Сколько потратил?", fake, session, journal_path=tmp_path / "trace.jsonl")
    assert "недоступен" in result
    assert json.loads(fake.messages_seen[1][-1]["content"])["error"]["type"] == "timeout"


def test_three_identical_calls_stop(loop, session, tmp_path):
    fake = ScriptedLLM([tool_reply("get_spending_summary", OCT, str(i)) for i in range(3)])
    out = loop.run_agent("Зациклился", fake, session, max_steps=5, journal_path=tmp_path / "trace.jsonl")
    assert out == loop.ESCALATE_TEXT


def test_max_steps_stops_alternating_calls(loop, session, tmp_path):
    fake = ScriptedLLM([
        tool_reply("get_spending_summary", OCT, "a"),
        tool_reply("get_spending_summary", {**OCT, "category": "food"}, "b"),
    ])
    out = loop.run_agent("Снова?", fake, session, max_steps=2, journal_path=tmp_path / "trace.jsonl")
    assert out == loop.LIMIT_TEXT


def test_action_rejection_does_not_modify_state(loop, session, tmp_path, tools):
    fake = ScriptedLLM([
        tool_reply("flag_subscription", {"subscription_id": tools._sub_id("Video Service", 100)}),
        {"content": "Не отмечена: пользователь отказался."},
    ])
    out = loop.run_agent("Отмени подписку", fake, session, confirm=lambda *_: False, journal_path=tmp_path / "trace.jsonl")
    assert "отказался" in out
    assert not session.flagged
