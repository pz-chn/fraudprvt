# test_retry_logic
# 不連資料庫, 用假造的例外檢查 is_retryable_db_error 的判斷規則
# 執行: uv run python test_retry_logic.py
from pymysql.err import OperationalError as PyMySQLOperationalError
from sqlalchemy.exc import IntegrityError, OperationalError

from crawler.db_retry import is_retryable_db_error


def fake_operational_error(code):
    # 與 SQLAlchemy 包裝 PyMySQL 錯誤的方式相同: orig 是 driver 原本的例外, args[0] 是錯誤碼
    return OperationalError("INSERT ...", {}, PyMySQLOperationalError(code, "fake"))


CASES = [
    ("OperationalError 1213 (deadlock)", fake_operational_error(1213), True),
    ("OperationalError 1205 (lock wait timeout)", fake_operational_error(1205), True),
    ("OperationalError 1045 (access denied)", fake_operational_error(1045), False),
    ("IntegrityError 1213", IntegrityError("INSERT ...", {}, PyMySQLOperationalError(1213, "fake")), False),
    ("ValueError", ValueError("not a db error"), False),
    ("RuntimeError", RuntimeError("cryptography package is required"), False),
]

failed = 0
for name, exc, expected in CASES:
    actual = is_retryable_db_error(exc)
    ok = actual is expected
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}: expected {expected}, got {actual}")

print(f"\n{len(CASES) - failed}/{len(CASES)} passed")
raise SystemExit(1 if failed else 0)
