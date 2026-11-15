"""Инструменты агента: схемы, проверка аргументов, права, ошибки, повторы."""
from __future__ import annotations

import csv
import json
import logging
import time
import zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

log = logging.getLogger(__name__)

Category = Literal["taxi", "food", "transfer", "subscription", "other"]
MAX_ITEMS = 50          # лимит размера результата
TIMEOUT_S = 3           # таймаут одного вызова
_sleep = time.sleep     # в тестах подменяем, чтобы не ждать

# Подмена сбоев для демо и тестов: {"имя_инструмента": ["timeout", "timeout"]}
FAULTS: dict[str, list[str]] = {}


class ServiceTimeout(Exception):
    pass


class ToolError(Exception):
    def __init__(self, type_: str, message: str, hint: str | None = None):
        self.type, self.message, self.hint = type_, message, hint


def err(type_: str, message: str, hint: str | None = None, **extra) -> dict:
    e = {"type": type_, "message": message, **extra}
    if hint:
        e["hint"] = hint
    return {"error": e}


@dataclass
class Session:
    """Клиент и его счёт берутся отсюда, а не от модели."""
    account_id: str
    statement_path: Path
    flagged: set = field(default_factory=set)


def load_operations(session: Session) -> list[dict]:
    with open(session.statement_path, encoding="utf-8", newline="") as f:
        return [
            {"op_id": r["op_id"], "date": date.fromisoformat(r["date"]),
             "amount_rub": float(r["amount_rub"]), "merchant": r["merchant"],
             "category": r["category"]}
            for r in csv.DictReader(f) if r["account_id"] == session.account_id
        ]


# ---------- схемы аргументов (одновременно проверка для кода) ----------

class GetSpendingSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date = Field(description="Начало периода, формат YYYY-MM-DD")
    date_to: date = Field(description="Конец периода включительно, формат YYYY-MM-DD")
    category: Category | None = Field(
        None, description="Категория. Если не указана, считаются все")

    @model_validator(mode="after")
    def _order(self):
        if self.date_from > self.date_to:
            raise ValueError("date_from позже date_to")
        return self


class FindRecurringPayments(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min_months: int = Field(
        3, ge=2, le=12, description="В скольких разных месяцах платёж должен встретиться")


class FlagSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subscription_id: str = Field(
        pattern=r"^sub_[0-9a-f]{8}$",
        description="id подписки из результата find_recurring_payments")


# ---------- функции инструментов ----------

def _sub_id(merchant: str) -> str:
    return f"sub_{zlib.crc32(merchant.encode()):08x}"


def get_spending_summary(args: GetSpendingSummary, session: Session) -> dict:
    ops = [o for o in load_operations(session)
           if args.date_from <= o["date"] <= args.date_to
           and (args.category is None or o["category"] == args.category)]
    if not ops:
        raise ToolError("not_found", "Нет операций за этот период и категорию",
                        "Уточни период или категорию у клиента")
    by_cat: dict[str, list[float]] = defaultdict(list)
    for o in ops:
        by_cat[o["category"]].append(o["amount_rub"])
    return {
        "period": {"from": args.date_from.isoformat(), "to": args.date_to.isoformat()},
        "total_rub": round(sum(o["amount_rub"] for o in ops), 2),   # сумму считает код
        "operations_count": len(ops),
        "by_category": [{"category": c, "total_rub": round(sum(v), 2), "count": len(v)}
                        for c, v in sorted(by_cat.items())],
    }


def _recurring(ops: list[dict], min_months: int) -> list[dict]:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for o in ops:
        groups[(o["merchant"], o["amount_rub"])].append(o)
    out = []
    for (merchant, amount), items in groups.items():
        months = {(o["date"].year, o["date"].month) for o in items}
        if len(months) >= min_months:
            out.append({"subscription_id": _sub_id(merchant), "merchant": merchant,
                        "amount_rub": amount, "months": len(months),
                        "last_date": max(o["date"] for o in items).isoformat()})
    return sorted(out, key=lambda x: x["merchant"])


def find_recurring_payments(args: FindRecurringPayments, session: Session) -> dict:
    ops = load_operations(session)
    seen: dict[tuple, int] = defaultdict(int)
    for o in ops:
        seen[(o["merchant"], o["amount_rub"], o["date"])] += 1
    dups = [{"merchant": m, "amount_rub": a, "date": d.isoformat(), "times": n}
            for (m, a, d), n in seen.items() if n > 1]
    recurring = _recurring(ops, args.min_months)
    return {"recurring": recurring[:MAX_ITEMS],
            "possible_duplicates": dups[:MAX_ITEMS],
            "note": f"показано до {MAX_ITEMS} записей"}


def flag_subscription(args: FlagSubscription, session: Session) -> dict:
    subs = {s["subscription_id"]: s for s in _recurring(load_operations(session), 2)}
    sub = subs.get(args.subscription_id)
    if sub is None:
        raise ToolError("not_found", "Нет такой подписки",
                        "Сначала вызови find_recurring_payments и возьми id оттуда")
    session.flagged.add(args.subscription_id)       # идемпотентно: повтор ничего не ломает
    return {"status": "flagged", "merchant": sub["merchant"],
            "amount_rub": sub["amount_rub"]}


# ---------- реестр ----------

@dataclass
class ToolSpec:
    model: type[BaseModel]
    fn: Callable
    kind: Literal["read", "action"]
    description: str


TOOLS: dict[str, ToolSpec] = {
    "get_spending_summary": ToolSpec(
        GetSpendingSummary, get_spending_summary, "read",
        "Возвращает траты клиента за период: общую сумму, число операций и разбивку по "
        "категориям. Используй для вопросов «сколько я потратил на X за период». Не "
        "используй для поиска подписок, для этого есть find_recurring_payments. Даты в "
        "формате YYYY-MM-DD. Если период не назван, спроси клиента."),
    "find_recurring_payments": ToolSpec(
        FindRecurringPayments, find_recurring_payments, "read",
        "Находит регулярные платежи (подписки) клиента и возможные дубли списаний. "
        "Используй, когда клиент спрашивает про подписки, регулярные или задвоенные "
        "платежи. Каждая подписка возвращается с subscription_id. Не возвращает суммы по "
        "категориям. Если клиент не уточнил, бери min_months=3."),
    "flag_subscription": ToolSpec(
        FlagSubscription, flag_subscription, "action",
        "Помечает подписку клиента как «отменить». Меняет данные, поэтому перед "
        "выполнением клиент подтвердит действие. Используй только после просьбы клиента, "
        "subscription_id бери из find_recurring_payments."),
}


def tool_schemas() -> list[dict]:
    return [{"type": "function",
             "function": {"name": n, "description": s.description,
                          "parameters": s.model.model_json_schema()}}
            for n, s in TOOLS.items()]


# ---------- выполнение ----------

def _call(name: str, spec: ToolSpec, args: BaseModel, session: Session):
    queue = FAULTS.get(name)
    if queue:
        kind = queue.pop(0)
        if kind == "timeout":
            raise ServiceTimeout(name)
        raise RuntimeError(f"тестовый сбой: {kind}")
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(spec.fn, args, session).result(timeout=TIMEOUT_S)
    except FutureTimeout:
        raise ServiceTimeout(name)
    finally:
        ex.shutdown(wait=False)


def execute_tool(name: str, raw_args, session: Session, confirm=None) -> dict:
    """Всегда возвращает словарь: {"result": ...}, {"error": ...} или {"cancelled": True}."""
    spec = TOOLS.get(name)
    if spec is None:
        return err("unknown_tool", f"Нет инструмента {name}", "Доступные: " + ", ".join(TOOLS))
    try:
        data = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args or {})
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, TypeError):
        return err("validation", "Аргументы должны быть JSON-объектом",
                   "Пришли аргументы в виде JSON-объекта по схеме")
    try:
        args = spec.model.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        return err("validation", first["msg"],
                   "Исправь аргумент по схеме инструмента и повтори вызов",
                   field=".".join(str(p) for p in first["loc"]) or "args")

    try:
        if spec.kind == "action":
            # действие: без подтверждения конкретных параметров не выполняем и не повторяем
            if confirm is None or not confirm(name, args.model_dump(mode="json")):
                return {"cancelled": True}
            try:
                return {"result": _call(name, spec, args, session)}
            except ServiceTimeout:
                return err("timeout", "Статус действия неизвестен",
                           "Не повторяй вызов. Предложи клиенту оператора")
        for i in range(3):                       # чтение: технический повтор с паузой
            try:
                return {"result": _call(name, spec, args, session)}
            except ServiceTimeout:
                if i < 2:
                    _sleep(0.5 * 2 ** i)
        return err("timeout", "Сервис операций не ответил", "Предложи клиенту оператора")
    except ToolError as e:
        return err(e.type, e.message, e.hint)
    except Exception:
        log.exception("tool %s failed", name)    # трассировка только в журнал
        return err("internal", "Внутренняя ошибка инструмента", "Передай вопрос оператору")
