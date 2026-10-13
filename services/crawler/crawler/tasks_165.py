# tasks_165
# 165 打詐儀錶板的案例摘要爬蟲
# 與 tasks.py (mygopen) 各自獨立, 寫入不同的表
from crawler.worker import app

import math
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import create_engine, text
from loguru import logger

from crawler.db_retry import MAX_DB_RETRIES, is_retryable_db_error, retry_countdown
from crawler.config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_ACCOUNT,
    MYSQL_PASSWORD,
    MYSQL_DATABASE,
)

API_URL = "https://165dashboard.tw/CIB_DWS_API/api/CaseSummary/GetCaseSummaryList"

# 這個 API 沒有分頁上限保護: request body 送 {} 會一次回傳全部 19 萬筆 (約 334MB),
# 所以每一次呼叫都必須帶 UsingPaging 參數
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60

TAIPEI_TZ = timezone(timedelta(hours=8))

# 來源 Id 是穩定且唯一的業務主鍵, 重跑同一頁走 UPDATE 而不是再插一筆
UPSERT_CASE_SQL = text("""
    INSERT INTO fraud_cases (id, case_date, city_id, city_name, case_title, summary)
    VALUES (:id, :case_date, :city_id, :city_name, :case_title, :summary)
    ON DUPLICATE KEY UPDATE
        case_date  = VALUES(case_date),
        city_id    = VALUES(city_id),
        city_name  = VALUES(city_name),
        case_title = VALUES(case_title),
        summary    = VALUES(summary)
""")


def request_page(page_index, page_size=PAGE_SIZE):
    response = requests.post(
        API_URL,
        json={
            "UsingPaging": True,
            "NumberOfPerPage": page_size,
            "PageIndex": page_index,
        },
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["body"]


def get_total_pages(page_size=PAGE_SIZE):
    # 用 page_size=1 只為了讀 RecordCount, 不把整頁資料拉下來
    # RecordCount 與 page_size 無關, TotalPages 則會跟著變, 所以自己換算
    record_count = request_page(1, page_size=1)["RecordCount"]
    total_pages = math.ceil(record_count / page_size)
    logger.info(f"來源共 {record_count} 筆, 以 {page_size} 筆/頁 分成 {total_pages} 頁")
    return total_pages


def parse_case_date(value):
    # 來源是 UTC: '2024-11-29T16:00:00Z' 其實是台北時間 2024-11-30
    # 必須換算時區再取日期, 直接截斷字串會讓整批日期往前偏一天
    return datetime.fromisoformat(value).astimezone(TAIPEI_TZ).date()


def clean_text(value):
    # 來源有 113 種 CaseTitle 前後帶著換行或 tab, 例如 '\n \t\n騙取金融帳戶(卡片)詐騙',
    # 不清掉會在 GROUP BY 時變成看起來重複的分類。
    # MySQL 的 PAD SPACE collation 只會忽略尾端空格, 換行與 tab 不會被忽略
    return value.strip() if isinstance(value, str) else value


def get_engine():
    return create_engine(
        f"mysql+pymysql://{MYSQL_ACCOUNT}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    )


def to_row(case):
    return {
        "id": int(case["Id"]),
        "case_date": parse_case_date(case["CaseDate"]),
        "city_id": case["CityId"],
        "city_name": clean_text(case["CityName"]),
        "case_title": clean_text(case["CaseTitle"]),
        "summary": clean_text(case["Summary"]),
    }


@app.task(bind=True)
def fetch_cases_page(self, page_index):
    logger.info(f"page {page_index}: 開始抓取")
    cases = request_page(page_index)["Detail"]

    if not cases:
        logger.info(f"page {page_index}: 沒有抓到資料")
        return 0

    rows = [to_row(case) for case in cases]

    engine = get_engine()
    try:
        # 整頁包在同一個交易裡, 中途失敗不會留下寫一半的頁
        with engine.begin() as conn:
            conn.execute(UPSERT_CASE_SQL, rows)
    except Exception as exc:
        if not is_retryable_db_error(exc):
            raise
        # 交易已整個 rollback, 重跑整頁即可; 次數用盡時 self.retry 會直接拋出原錯誤
        if self.request.retries < MAX_DB_RETRIES:
            logger.warning(
                f"{self.name} page {page_index}: 第 {self.request.retries + 1} 次重試, "
                f"MySQL 錯誤碼 {exc.orig.args[0]}"
            )
        raise self.retry(
            exc=exc,
            countdown=retry_countdown(self.request.retries),
            max_retries=MAX_DB_RETRIES,
        )

    logger.info(f"page {page_index}: 寫入 {len(rows)} 筆資料")
    return len(rows)
