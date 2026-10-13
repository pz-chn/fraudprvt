# producer_165
# 把 165 案例摘要的分頁任務送進 RabbitMQ
# 用法:
#   uv run python -m crawler.producer_165        # 全量: 派送所有頁
#   uv run python -m crawler.producer_165 3      # 增量: 只派送最後 3 頁
#
# 增量只抓尾端是因為來源的 Id 遞增、資料只會往後追加,
# 新案例一定落在最後幾頁, 前面的頁內容不會變動
import sys

from loguru import logger

from crawler.tasks_165 import fetch_cases_page, get_total_pages


# 抽成函式, 讓 tasks_schedule.py 的定時任務也能共用同一段派工邏輯
def dispatch_pages(tail_pages=None):
    total_pages = get_total_pages()
    start_page = max(1, total_pages - tail_pages + 1) if tail_pages else 1

    logger.info(f"派送 page {start_page} ~ {total_pages}")
    for page in range(start_page, total_pages + 1):
        fetch_cases_page.delay(page)


if __name__ == "__main__":
    dispatch_pages(int(sys.argv[1]) if len(sys.argv) > 1 else None)
