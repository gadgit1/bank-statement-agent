"""Bank statement CLI: real GigaChat tool calling, human confirmation and trace."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

from llm import GigaChatLLM, StubLLM
from loop import run_agent
from tools import FAULTS, TOOLS, Session, _recurring, load_operations


def confirm_action(name: str, args: dict, session: Session) -> bool:
    """Show the exact action parameters; never interpret model text as consent."""
    print(f"\nПодтверждение действия: {name}")
    if name == "flag_subscription":
        sub = next((item for item in _recurring(load_operations(session), 2)
                    if item["subscription_id"] == args.get("subscription_id")), None)
        if sub is None:
            print("Подписка не найдена. Действие не выполнено.")
            return False
        print(f"Подписка: {sub['merchant']} · {sub['amount_rub']:.2f} ₽")
        print(f"Идентификатор: {sub['subscription_id']}")
        print("Будет сохранена только локальная отметка, без отмены банковских списаний.")
    else:
        print(f"Параметры: {args}")
    return input("Подтвердить? [y/N]: ").strip().lower() in {"y", "yes", "да"}


def _args():
    parser = argparse.ArgumentParser(description="Аналитик банковской выписки · HW1")
    parser.add_argument("--config", default="config.yaml", help="путь к конфигурации")
    parser.add_argument("--provider", choices=("gigachat", "stub"), help="переопределить провайдера")
    parser.add_argument("--model", help="переопределить модель")
    parser.add_argument("--message", help="один вопрос вместо интерактивного чата")
    parser.add_argument("--check-connection", action="store_true", help="проверить доступ к выбранной модели GigaChat")
    parser.add_argument("--fault-timeout", choices=[n for n, spec in TOOLS.items() if spec.kind == "read"],
                        help="для проверки надёжности: вызвать 3 таймаута инструмента чтения")
    parser.add_argument("--trace", default="logs/trace.jsonl", help="путь к JSONL-журналу")
    parser.add_argument("--show-tools", action="store_true", help="показать инструменты, выбранные LLM в этом запросе")
    return parser.parse_args()


def main() -> int:
    args = _args()
    load_dotenv(".env")
    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    provider = args.provider or config["provider"]
    model = args.model or config["model"]
    if provider not in ("gigachat", "stub"):
        print(f"Неизвестный провайдер: {provider}", file=sys.stderr)
        return 2

    try:
        llm = GigaChatLLM(model) if provider == "gigachat" else StubLLM()
    except (ImportError, RuntimeError, ValueError) as exc:
        print(f"Ошибка настройки: {exc}", file=sys.stderr)
        return 2

    if args.check_connection:
        if provider != "gigachat":
            print("Проверка API доступна только для провайдера gigachat", file=sys.stderr)
            return 2
        try:
            llm.check_connection()
            print(f"GigaChat API доступен, модель {model} доступна.")
            return 0
        except Exception as exc:
            print(f"GigaChat недоступен ({type(exc).__name__}). Проверьте сеть, модель и сертификат.", file=sys.stderr)
            return 2

    session = Session(account_id=config["account_id"], statement_path=Path(config["statement_path"]))
    if not session.statement_path.exists():
        print(f"Не найдена выписка: {session.statement_path}. Выполните python make_statement.py", file=sys.stderr)
        return 2
    if args.fault_timeout:
        FAULTS[args.fault_timeout] = ["timeout"] * 3
        print(f"Тест отказоустойчивости: 3 таймаута {args.fault_timeout}")

    def ask(question: str) -> bool:
        trace_path = Path(args.trace)
        old_size = trace_path.stat().st_size if trace_path.exists() else 0
        try:
            answer = run_agent(question, llm, session,
                               confirm=lambda name, params: confirm_action(name, params, session),
                               journal_path=args.trace)
        except (KeyboardInterrupt, EOFError):
            print("\nПрервано пользователем")
            return False
        except Exception as exc:
            # Do not leak credentials or stack traces to the end user.
            print(f"GigaChat не ответил ({type(exc).__name__}). Повторите запрос позже.", file=sys.stderr)
            return False
        print("Агент:", answer)
        if args.show_tools:
            if trace_path.exists():
                with trace_path.open("r", encoding="utf-8") as file:
                    file.seek(old_size)
                    rows = [json.loads(line) for line in file if line.strip()]
            else:
                rows = []
            if rows:
                for row in rows:
                    print(f"  ↳ инструмент: {row['tool']} | шаг {row['step']} | "
                          f"{row['error'] or 'успех'} | {row['duration_ms']} мс")
            else:
                print("  ↳ инструменты не вызывались")
        return True

    if args.message is not None:
        return 0 if ask(args.message) else 2

    print(f"Аналитик выписки · {provider} / {model}")
    print("Введите вопрос. Команда 'выход' завершает сеанс.")
    while True:
        try:
            question = input("\nВы: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if question.lower() in {"выход", "exit", "quit"}:
            break
        if question:
            ask(question)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
