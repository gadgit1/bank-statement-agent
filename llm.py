"""GigaChat function-calling adapter and a deterministic offline test double."""
from __future__ import annotations
import json
import os


def _call(name, arguments, idx):
    return {"content": None, "tool_calls": [{"id": f"call_{idx}", "name": name,
                                             "arguments": json.dumps(arguments, ensure_ascii=False)}]}


class StubLLM:
    """Scripted smoke-test, not a real LLM; use GigaChat for final demo."""
    def chat(self, messages, tools):
        user = next(m["content"] for m in messages if m["role"] == "user").lower()
        last = messages[-1]
        if last["role"] == "tool":
            data = json.loads(last["content"])
            if "error" in data:
                return {"content": "Инструмент недоступен или вернул ошибку. Не могу назвать точную сумму; обратитесь к оператору или попробуйте позже."}
            if data.get("cancelled"):
                return {"content": "Действие отменено: подтверждения нет. Подписка не помечена."}
            result = data.get("result", {})
            if "total_rub" in result:
                return {"content": f"По выписке расходы: {result['total_rub']:.2f} ₽, операций: {result['operations_count']}."}
            if "status" in result:
                return {"content": f"Подписка {result['merchant']} помечена к отмене только в текущей сессии; списания в банке не отменены."}
            if "recurring" in result:
                if any(word in user for word in ("отмен", "помет")):
                    selected = result["recurring"]
                    if "video" in user:
                        selected = [s for s in selected if "video" in s["merchant"].lower()]
                    if not selected:
                        return {"content": "Подходящая подписка не найдена."}
                    return _call("flag_subscription", {"subscription_id": selected[0]["subscription_id"]}, len(messages))
                names = [f"{s['merchant']} ({s['amount_rub']} ₽)" for s in result["recurring"]]
                return {"content": "Регулярные платежи: " + (", ".join(names) if names else "не найдены") + f". Возможных дублей: {len(result['possible_duplicates'])}."}
        if any(word in user for word in ("подпис", "дубл", "регуляр", "отмен", "помет")):
            return _call("find_recurring_payments", {"min_months": 3}, len(messages))
        if any(word in user for word in ("потрат", "трат", "расход", "такси")):
            category = "taxi" if "такси" in user else None
            return _call("get_spending_summary", {"date_from": "2026-10-01", "date_to": "2026-10-31", "category": category}, len(messages))
        return {"content": "Это учебный stub: спросите о тратах на такси за октябрь 2026 или о подписках. Для свободного диалога используйте provider: gigachat."}


class GigaChatLLM:
    """Adapter for gigachat==0.2.4. GigaChat chooses the next tool; code executes it."""

    def __init__(self, model: str):
        from pathlib import Path
        from gigachat import GigaChat

        credentials = os.getenv("GIGACHAT_CREDENTIALS", "").strip()
        if not credentials:
            raise RuntimeError("Нет GIGACHAT_CREDENTIALS: создайте .env по .env.example")
        ca_file = os.getenv("GIGACHAT_CA_BUNDLE_FILE", "").strip()
        if ca_file and not Path(ca_file).is_file():
            raise RuntimeError(f"CA-сертификат не найден: {ca_file} (см. README)")
        self.model = model
        self.client = GigaChat(
            credentials=credentials,
            model=model,
            scope=os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS"),
            ca_bundle_file=ca_file or None,
            timeout=float(os.getenv("GIGACHAT_TIMEOUT", "45")),
            max_retries=0,  # One timeout should not silently multiply into minutes.
        )

    def check_connection(self) -> list[str]:
        """Check the REAL API and model access; do not print credentials or tokens."""
        models = [m.id_ for m in self.client.get_models().data]
        if self.model not in models:
            raise RuntimeError(f"Модель {self.model} недоступна; доступные: {', '.join(models)}")
        return models

    def chat(self, messages, tools):
        from gigachat.models import Chat, Messages, MessagesRole, Function, FunctionCall, FunctionParameters

        # The harness uses OpenAI-style tool messages. The GigaChat SDK expects
        # assistant function_call + role=function with a function name.
        id_to_name: dict[str, str] = {}
        history = []
        for message in messages:
            role = message["role"]
            if role in ("system", "user"):
                history.append(Messages(role=MessagesRole(role), content=message["content"]))
            elif role == "assistant":
                calls = message.get("tool_calls") or []
                if calls:
                    if len(calls) > 1:
                        raise ValueError("GigaChat adapter supports one function call per model turn")
                    call = calls[0]
                    function = call["function"]
                    id_to_name[call["id"]] = function["name"]
                    args = function["arguments"]
                    history.append(Messages(
                        role=MessagesRole.ASSISTANT,
                        content=message.get("content") or "",
                        function_call=FunctionCall(
                            name=function["name"],
                            arguments=json.loads(args) if isinstance(args, str) else args,
                        ),
                    ))
                else:
                    history.append(Messages(role=MessagesRole.ASSISTANT, content=message.get("content") or ""))
            elif role == "tool":
                name = id_to_name.get(message["tool_call_id"])
                if not name:
                    raise ValueError("Tool response has an unknown tool_call_id")
                history.append(Messages(role=MessagesRole.FUNCTION, name=name, content=message["content"]))

        functions = []
        for tool in tools:
            definition = tool["function"]
            schema = definition["parameters"]
            properties = {}
            for key, field in schema.get("properties", {}).items():
                # The GigaChat schema is intentionally simpler than Pydantic's
                # JSON schema. Pydantic still validates EVERY received argument.
                if key == "category":
                    properties[key] = {
                        "type": "string",
                        "enum": ["taxi", "food", "transfer", "subscription", "other"],
                        "description": "Категория расходов; можно опустить",
                    }
                elif key == "min_months":
                    properties[key] = {
                        "type": "integer", "minimum": 2, "maximum": 12,
                        "description": "Минимальное число разных месяцев, от 2 до 12",
                    }
                else:
                    properties[key] = {
                        "type": "string",
                        "description": field.get("description", ""),
                    }
            functions.append(Function(
                name=definition["name"], description=definition["description"],
                parameters=FunctionParameters(
                    type="object", properties=properties, required=schema.get("required", []),
                ),
            ))

        response = self.client.chat(Chat(
            messages=history, functions=functions, model=self.model,
        ))
        message = response.choices[0].message
        if message.function_call is not None:
            arguments = message.function_call.arguments or {}
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            return _call(message.function_call.name, arguments, len(messages))
        return {"content": message.content or "", "tool_calls": []}
