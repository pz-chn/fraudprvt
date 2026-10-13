# tasks
# 從 worker.py 匯入 Celery app 實例
# 所有的 task 都要透過 app 來註冊, 才能被 Celery worker 識別
from crawler.worker import app

import re
from datetime import datetime, timedelta, timezone

import feedparser
from bs4 import BeautifulSoup
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

BASE_URL = "https://www.mygopen.com/feeds/posts/default"
MAX_RESULTS = 25

TAIPEI_TZ = timezone(timedelta(hours=8))

# MyGoPen 的標題格式固定是「【錯誤】網傳...」, 前面的標籤就是查核結果
VERDICT_PATTERN = re.compile(r"^【(.+?)】")


# url 是這張表的業務主鍵, 重跑同一頁時走 UPDATE 而不是再插一筆
# 這裡的「相同」由 url 欄位的 collation 決定, 必須是 utf8mb4_bin:
# venezuela.html 與 Venezuela.html 是兩篇不同的文章, 用不分大小寫的
# collation 會讓後抓到的那篇覆蓋掉前一篇
UPSERT_ARTICLE_SQL = text("""
    INSERT INTO mygopen_articles (title, verdict, published, url, content_text)
    VALUES (:title, :verdict, :published, :url, :content_text)
    ON DUPLICATE KEY UPDATE
        title        = VALUES(title),
        verdict      = VALUES(verdict),
        published    = VALUES(published),
        content_text = VALUES(content_text)
""")

# ON DUPLICATE KEY UPDATE 之後 LAST_INSERT_ID() 不可靠, 直接用 url 查回 id
SELECT_ARTICLE_ID_SQL = text("SELECT id FROM mygopen_articles WHERE url = :url")

# 先清掉舊分類再寫入, 這樣上游改掉標籤時不會殘留
DELETE_CATEGORIES_SQL = text("DELETE FROM article_categories WHERE article_id = :article_id")

INSERT_CATEGORY_SQL = text("""
    INSERT INTO article_categories (article_id, category)
    VALUES (:article_id, :category)
""")


def clean_html(raw_html):
    # 把 RSS 內容裡的 HTML 標籤清掉, 只留下純文字
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def extract_verdict(title):
    match = VERDICT_PATTERN.match(title or "")
    return match.group(1) if match else None


def parse_published(value):
    # RSS 給的是 '2026-08-22T11:00:53.497+08:00'
    # 統一換算成台北時間後存成 naive datetime, 避免上游換時區時資料對不起來
    published = datetime.fromisoformat(value)
    if published.tzinfo is not None:
        published = published.astimezone(TAIPEI_TZ).replace(tzinfo=None)
    # DATETIME 只存到秒, 自己截斷毫秒以免 MySQL 四捨五入後與 migration 的回填值差一秒
    return published.replace(microsecond=0)


def get_engine():
    return create_engine(
        f"mysql+pymysql://{MYSQL_ACCOUNT}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    )


# @app.task() 是 Celery 的裝飾器 (decorator)
# 有了這個裝飾器, 普通的 Python 函式就會變成「可派送的任務」
@app.task(bind=True)
def fetch_page(self, page):
    # 對應 test_mygopen_crawler-0912.py 裡「抓一頁」的邏輯
    start_index = page * MAX_RESULTS + 1
    url = f"{BASE_URL}?start-index={start_index}&max-results={MAX_RESULTS}"

    logger.info(f"page {page}: 開始抓取 {url}")
    feed = feedparser.parse(url)

    articles = []
    for entry in feed.entries:
        articles.append({
            "title": entry.title,
            "verdict": extract_verdict(entry.title),
            "published": parse_published(entry.published),
            "url": entry.link,
            "content_text": clean_html(entry.content[0].value) if "content" in entry else "",
            # categories 不是 mygopen_articles 的欄位, 分開寫進 article_categories
            "categories": sorted({tag.term.strip() for tag in entry.get("tags", []) if tag.term.strip()}),
        })

    if not articles:
        logger.info(f"page {page}: 沒有抓到資料")
        return 0

    engine = get_engine()
    try:
        # 整頁包在同一個交易裡, 中途失敗不會留下只有文章沒有分類的半套資料
        with engine.begin() as conn:
            for article in articles:
                categories = article.pop("categories")
                conn.execute(UPSERT_ARTICLE_SQL, article)

                article_id = conn.execute(
                    SELECT_ARTICLE_ID_SQL, {"url": article["url"]}
                ).scalar()

                conn.execute(DELETE_CATEGORIES_SQL, {"article_id": article_id})
                if categories:
                    conn.execute(
                        INSERT_CATEGORY_SQL,
                        [
                            {"article_id": article_id, "category": category}
                            for category in categories
                        ],
                    )
    except Exception as exc:
        if not is_retryable_db_error(exc):
            raise
        # 交易已整個 rollback, 重跑整頁即可; 次數用盡時 self.retry 會直接拋出原錯誤
        if self.request.retries < MAX_DB_RETRIES:
            logger.warning(
                f"{self.name} page {page}: 第 {self.request.retries + 1} 次重試, "
                f"MySQL 錯誤碼 {exc.orig.args[0]}"
            )
        raise self.retry(
            exc=exc,
            countdown=retry_countdown(self.request.retries),
            max_retries=MAX_DB_RETRIES,
        )

    logger.info(f"page {page}: 寫入 {len(articles)} 筆資料")
    return len(articles)
