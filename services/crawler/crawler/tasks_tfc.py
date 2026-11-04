# tasks_tfc
# 台灣事實查核中心 (TFC) 的查核報告爬蟲
# 網站是 WordPress, 直接用內建的 REST API 取資料, 比 RSS 完整 (RSS 只有摘要沒有全文)
# 與 tasks.py (mygopen) 各自獨立, 寫入不同的表
from crawler.worker import app

import html
from datetime import datetime

import requests
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

API_BASE = "https://tfc-taiwan.org.tw/wp-json/wp/v2"
# 查核報告是自訂的文章類型, 不在一般文章 (/posts) 裡
REPORTS_URL = f"{API_BASE}/fact-check-reports"

# 查核結果 (錯誤 / 部分錯誤 / 事實釐清 ...) 與報告類型 (生活 / 國際 ...) 各是一種分類
VERDICT_TAXONOMY = "fact-check-report-classification"
CATEGORY_TAXONOMY = "fact-check-report-type"

# 一篇的 HTML 約 90KB, 一頁 100 篇就有約 10MB; 20 篇一頁比較不會逾時
PAGE_SIZE = 20
REQUEST_TIMEOUT = 60

# 只拿需要的欄位
# 注意: 用 _fields 時 taxonomy_info (分類的中文名稱) 會變成空的,
# 所以查核結果與類型改拿分類 ID, 再用 get_term_names 對照成中文
FIELDS = f"id,date,modified,link,title,content,{VERDICT_TAXONOMY},{CATEGORY_TAXONOMY}"

# 全量依 id 排序: 抓取期間有文章被修改, 頁面也不會位移而漏抓
# 每日依修改時間排序: 新文章與被修改的舊文章都會排在最前面
ORDER_FULL = {"orderby": "id", "order": "asc"}
ORDER_RECENT = {"orderby": "modified", "order": "desc"}

# source_id 是 TFC 自己的文章編號, 也是這張表的主鍵, 重跑同一頁時走 UPDATE
# 不用 url 當判斷依據: WordPress 的網址由 slug 產生, 編輯改了 slug 就會變
UPSERT_ARTICLE_SQL = text("""
    INSERT INTO tfc_articles (source_id, title, verdict, published, modified, url, content_text)
    VALUES (:source_id, :title, :verdict, :published, :modified, :url, :content_text)
    ON DUPLICATE KEY UPDATE
        title        = VALUES(title),
        verdict      = VALUES(verdict),
        published    = VALUES(published),
        modified     = VALUES(modified),
        url          = VALUES(url),
        content_text = VALUES(content_text)
""")

# 先清掉舊分類再寫入, 這樣上游改掉類型時不會殘留
DELETE_CATEGORIES_SQL = text("DELETE FROM tfc_article_categories WHERE article_id = :article_id")

INSERT_CATEGORY_SQL = text("""
    INSERT INTO tfc_article_categories (article_id, category)
    VALUES (:article_id, :category)
""")


def request_reports(page, per_page=PAGE_SIZE, order=ORDER_RECENT, fields=FIELDS):
    # WordPress 的 page 從 1 開始; 超過最後一頁會回 400
    response = requests.get(
        REPORTS_URL,
        params={"per_page": per_page, "page": page, "_fields": fields, **order},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response


def get_total_pages(page_size=PAGE_SIZE):
    # 總篇數與總頁數直接寫在回應標頭, 只拿 id 欄位, 不把全文拉下來
    response = request_reports(1, per_page=page_size, fields="id")
    total = int(response.headers["X-WP-Total"])
    total_pages = int(response.headers["X-WP-TotalPages"])
    logger.info(f"TFC 查核報告共 {total} 篇, 以 {page_size} 篇/頁 分成 {total_pages} 頁")
    return total_pages


def get_term_names(taxonomy):
    # 分類只有十幾個, 一次拿完做成 {ID: 中文名稱} 的對照表
    response = requests.get(
        f"{API_BASE}/{taxonomy}",
        params={"per_page": 100, "_fields": "id,name"},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return {term["id"]: html.unescape(term["name"]) for term in response.json()}


def clean_html(raw_html):
    # 與 tasks.py 相同只留純文字; 另外先拿掉 <style> / <script>,
    # 這個網站的頁面內嵌了排版用的 CSS, 不拿掉會變成內文的一部分
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup(["style", "script"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def to_article(report, verdict_names, category_names):
    verdicts = [verdict_names.get(i) for i in report.get(VERDICT_TAXONOMY, [])]
    categories = {(category_names.get(i) or "").strip() for i in report.get(CATEGORY_TAXONOMY, [])}
    return {
        "source_id": report["id"],
        # 標題的引號等符號可能是 HTML 實體 (例如 &#8220;), 換回原本的字
        "title": html.unescape(report["title"]["rendered"]),
        "verdict": next((v for v in verdicts if v), None),
        # API 的 date / modified 已經是台北時間且不帶時區, 與 mygopen 存法一致
        "published": datetime.fromisoformat(report["date"]),
        "modified": datetime.fromisoformat(report["modified"]),
        "url": report["link"],
        "content_text": clean_html(report["content"]["rendered"]),
        # categories 不是 tfc_articles 的欄位, 分開寫進 tfc_article_categories
        "categories": sorted(c for c in categories if c),
    }


def get_engine():
    return create_engine(
        f"mysql+pymysql://{MYSQL_ACCOUNT}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4"
    )


@app.task(bind=True)
def fetch_tfc_page(self, page, full=False):
    order = ORDER_FULL if full else ORDER_RECENT
    logger.info(f"TFC page {page}: 開始抓取 (排序 {order['orderby']})")
    reports = request_reports(page, order=order).json()

    if not reports:
        logger.info(f"TFC page {page}: 沒有抓到資料")
        return 0

    verdict_names = get_term_names(VERDICT_TAXONOMY)
    category_names = get_term_names(CATEGORY_TAXONOMY)
    articles = [to_article(report, verdict_names, category_names) for report in reports]

    engine = get_engine()
    try:
        # 整頁包在同一個交易裡, 中途失敗不會留下只有文章沒有分類的半套資料
        with engine.begin() as conn:
            for article in articles:
                categories = article.pop("categories")
                conn.execute(UPSERT_ARTICLE_SQL, article)

                # 主鍵就是來源編號, 不用像 tasks.py 那樣再查一次 id
                article_id = article["source_id"]
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

    logger.info(f"TFC page {page}: 寫入 {len(articles)} 筆資料")
    return len(articles)
