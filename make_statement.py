"""Создать СИНТЕТИЧЕСКУЮ CSV-выписку для локального тестирования (без персональных данных)."""
import csv
from pathlib import Path

PATH = Path("data/sample_statement.csv")

def main():
    PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("demo-account", "s08", "2026-08-05", 299, "Video Service", "subscription"),
        ("demo-account", "s09", "2026-09-05", 299, "Video Service", "subscription"),
        ("demo-account", "s10", "2026-10-05", 299, "Video Service", "subscription"),
        ("demo-account", "m08", "2026-08-10", 129, "Music Service", "subscription"),
        ("demo-account", "m09", "2026-09-10", 129, "Music Service", "subscription"),
        ("demo-account", "m10", "2026-10-10", 129, "Music Service", "subscription"),
        ("demo-account", "t01", "2026-10-12", 250, "Taxi Go", "taxi"),
        ("demo-account", "t02", "2026-10-18", 350, "Taxi Go", "taxi"),
        ("demo-account", "f01", "2026-10-20", 750, "Grocery Store", "food"),
        ("demo-account", "in1", "2026-10-21", -3000, "Incoming transfer", "transfer"),
        ("demo-account", "f02", "2026-10-22", 500, "Cafe", "food"),
        ("demo-account", "d01", "2026-10-25", 150, "Cloud Provider", "other"),
        ("demo-account", "d02", "2026-10-25", 150, "Cloud Provider", "other"),
        ("other-account", "secret", "2026-10-12", 999999, "Private Vendor", "taxi"),
    ]
    with PATH.open("w", encoding="utf-8", newline="") as file:
        writer=csv.writer(file)
        writer.writerow(["account_id", "op_id", "date", "amount_rub", "merchant", "category"])
        writer.writerows(rows)
    print(f"Created {PATH} ({len(rows)} operations including foreign-account row)")

if __name__ == "__main__":
    main()
