# producer_tfc
# 把台灣事實查核中心 (TFC) 查核報告的分頁任務送進 RabbitMQ
# 用法:
#   uv run python -m crawler.producer_tfc        # 全量: 依 id 排序派送所有頁
#   uv run python -m crawler.producer_tfc 3      # 增量: 依修改時間排序, 只派送最前面 3 頁
#
# 增量取「最前面」而不是 165 的「最後面」:
# 依修改時間由新到舊排序, 新文章與剛被修改的舊文章都會落在前幾頁
import sys

from loguru import logger

from crawler.tasks_tfc import fetch_tfc_page, get_total_pages


# 抽成函式, 讓 tasks_schedule.py 的定時任務也能共用同一段派工邏輯
def dispatch_pages(head_pages=None):
    total_pages = get_total_pages()
    full = head_pages is None
    last_page = total_pages if full else min(head_pages, total_pages)

    logger.info(f"派送 TFC page 1 ~ {last_page} ({'全量' if full else '增量'})")
    for page in range(1, last_page + 1):
        fetch_tfc_page.delay(page, full)


if __name__ == "__main__":
    dispatch_pages(int(sys.argv[1]) if len(sys.argv) > 1 else None)
