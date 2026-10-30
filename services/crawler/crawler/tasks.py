# tasks
# 從 worker.py 匯入 Celery app 實例
# 所有的 task 都要透過 app 來註冊, 才能被 Celery worker 識別
from crawler.worker import app

import re # 正規表達式(regular expression) 用規則從文字裡找東西
from datetime import datetime, timedelta, timezone # datetime時間點 timedelta一段時間長度 timezone時區

import feedparser # 讀rss用(網站提供的「最新文章清單」，格式固定，比直接爬網頁穩定)
from bs4 import BeautifulSoup # 解析html用
from sqlalchemy import create_engine, text # create_engine建立mysql連線用 text把 SQL 字串包起來，讓 sqlalchemy 認得它是 SQL
from loguru import logger # 印log用

from crawler.db_retry import MAX_DB_RETRIES, is_retryable_db_error, retry_countdown # claude寫的死鎖處理工具
from crawler.config import (
    MYSQL_HOST,
    MYSQL_PORT,
    MYSQL_ACCOUNT,
    MYSQL_PASSWORD,
    MYSQL_DATABASE,
) # 環境變數

BASE_URL = "https://www.mygopen.com/feeds/posts/default"
MAX_RESULTS = 25

TAIPEI_TZ = timezone(timedelta(hours=8))

# MyGoPen 的標題格式固定是「【錯誤】網傳...」, 前面的標籤就是查核結果
VERDICT_PATTERN = re.compile(r"^【(.+?)】")


# url 是這張表的業務主鍵, 重跑同一頁時走 UPDATE 而不是再插一筆
# 這裡的「相同」由 url 欄位的 collation(校對／定序規則 文字比對與排序的機制) 決定, 必須是 utf8mb4_bin:
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
    soup = BeautifulSoup(raw_html, "html.parser") #  HTML 解析成可以操作的結構 輸入：<p>網傳<b>喝熱水</b>可以殺死病毒</p><p>這是錯誤的</p>
    return soup.get_text(separator=" ", strip=True) # 輸出：網傳 喝熱水 可以殺死病毒 這是錯誤的


def extract_verdict(title):
    match = VERDICT_PATTERN.match(title or "") # 用正規表達式檢查標題 格式相符的話會得到 match 物件，不符合就是 None
    return match.group(1) if match else None # group(1) 取出【】裡面的字


def parse_published(value):
    # RSS 給的是 '2026-08-22T11:00:53.497+08:00'
    # 統一換算成台北時間後存成 naive datetime, 避免上游換時區時資料對不起來
    published = datetime.fromisoformat(value) # 2026-08-22 11:00:53.497  時區 +08:00
    if published.tzinfo is not None: # 如果有帶時區
        published = published.astimezone(TAIPEI_TZ).replace(tzinfo=None) # astimezone(taipei_tz)換成台北時區 replace(tzinfo=none)把時區資訊拿掉 2026-08-22 11:00:53.497
    # DATETIME 只存到秒；MySQL 會四捨五入，所以這裡自己先把毫秒捨去，以免 MySQL 四捨五入後與 migration 的回填值差一秒
    return published.replace(microsecond=0)


def get_engine():
    return create_engine(
        f"mysql+pymysql://{MYSQL_ACCOUNT}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    ) #engine：sqlalchemy 的「連線管理器」，之後用 engine.begin() 從它取得連線


# @app.task() 是 Celery 的裝飾器 (decorator)
# 有了這個裝飾器, 普通的 Python 函式就會變成「可派送的任務」
@app.task(bind=True)
def fetch_page(self, page):
    # 「抓一頁」的邏輯
    start_index = page * MAX_RESULTS + 1 #page是producer送過來的 producer從0開始數 rss從1開始數 index是要抓的第一筆 每頁 25 筆，所以 page 1 從第 26 筆開始
    url = f"{BASE_URL}?start-index={start_index}&max-results={MAX_RESULTS}"

    logger.info(f"page {page}: 開始抓取 {url}")
    feed = feedparser.parse(url) #開始下載和解析rss

    articles = [] #準備一個空list來放文章
    for entry in feed.entries:
        articles.append({ #把整理好的dict加進lst
            "title": entry.title, #【錯誤】網傳喝熱水可以殺死病毒
            "verdict": extract_verdict(entry.title), #錯誤
            "published": parse_published(entry.published), #parse_published("2026-08-22T11:00:53.497+08:00")  → datetime(2026, 8, 22, 11, 0, 53)>>2026-08-22 11:00:53
            "url": entry.link,
            "content_text": clean_html(entry.content[0].value) if "content" in entry else "", #如果有content就拿出第1個value 再去掉html標籤
            # categories 不是 mygopen_articles 的欄位, 分開寫進 article_categories
            "categories": sorted({tag.term.strip() for tag in entry.get("tags", []) if tag.term.strip()}),
        })

    if not articles: #list是空的
        logger.info(f"page {page}: 沒有抓到資料")
        return 0

    engine = get_engine()
    try: #試著做 如果中間error 就跳到下面的except
        # 整頁包在同一個交易裡, 中途失敗不會留下只有文章沒有分類的半套資料
        with engine.begin() as conn: #這條連線叫conn
            for article in articles:
                categories = article.pop("categories") #pop把這個 key 從 dict 裡拿出來，並且刪掉 mygopen_articles沒有categories欄位所以要pop掉
                conn.execute(UPSERT_ARTICLE_SQL, article) #新增或更新文章 執行 SQL，把 dict 的值填進同名的空格

                article_id = conn.execute(
                    SELECT_ARTICLE_ID_SQL, {"url": article["url"]}
                ).scalar() #查id scalar純量

                conn.execute(DELETE_CATEGORIES_SQL, {"article_id": article_id}) #刪掉這篇的舊分類
                if categories: #有分類才寫入
                    conn.execute(
                        INSERT_CATEGORY_SQL,
                        [
                            {"article_id": article_id, "category": category}
                            for category in categories
                        ],
                    )
    except Exception as exc: #error存在exc
        if not is_retryable_db_error(exc): #exc是要重試的error嗎? 不是的話走下一行raise
            raise # 把錯誤原封不動丟出去，任務失敗，函式結束
        # 交易已整個 rollback, 重跑整頁即可; 次數用盡時 self.retry 會直接拋出原錯誤
        if self.request.retries < MAX_DB_RETRIES:
            logger.warning(
                f"{self.name} page {page}: 第 {self.request.retries + 1} 次重試, "
                f"MySQL 錯誤碼 {exc.orig.args[0]}"
            )
        raise self.retry(
            exc=exc, #死鎖的error 如果重試的次數用完就丟出這個error
            countdown=retry_countdown(self.request.retries), #幾秒後重試
            max_retries=MAX_DB_RETRIES, #最多重試5次
        )

    logger.info(f"page {page}: 寫入 {len(articles)} 筆資料")
    return len(articles)
