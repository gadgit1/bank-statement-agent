"""CLI smoke tests run against a test double, never a paid API."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def cli(*args):
    return subprocess.run([sys.executable, "main.py", "--provider", "stub", *args],
                          cwd=ROOT, capture_output=True, text=True, check=True)


def test_cli_spending_and_handled_timeout():
    answer = cli("--message", "Сколько я потратил на такси в октябре 2026?")
    assert "600.00" in answer.stdout
    error = cli("--fault-timeout", "get_spending_summary", "--message",
                "Сколько я потратил на такси в октябре 2026?")
    assert "не могу назвать точную сумму" in error.stdout.lower()


def test_cli_recurring_and_duplicates():
    answer = cli("--message", "Какие у меня подписки и возможные дубли?")
    assert "Video Service" in answer.stdout
    assert "Music Service" in answer.stdout
    assert "дублей: 1" in answer.stdout


def test_cli_help():
    help_result = subprocess.run([sys.executable, "main.py", "--help"],
                                 cwd=ROOT, capture_output=True, text=True, check=True)
    assert "--check-connection" in help_result.stdout


def test_cli_shows_selected_tool_name():
    answer = cli("--show-tools", "--message", "Сколько я потратил на такси в октябре 2026?")
    assert "инструмент: get_spending_summary" in answer.stdout
