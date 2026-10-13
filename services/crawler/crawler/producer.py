# producer
# Producer (生產者): 負責把任務送進 RabbitMQ 佇列
# 對應的 Consumer (消費者) 就是 worker.py 啟動的 Celery worker
# 流程: producer.py → RabbitMQ (訊息佇列) → worker 取出並執行任務

# 從 tasks.py 匯入 fetch_page 這個 Celery task 函式
from crawler.tasks import fetch_page

# 分成 5 頁, 每一頁是一個獨立任務, 各自送進佇列
# worker 會依序 (或同時, 如果之後開多個 worker) 把它們拿去執行
TOTAL_PAGES = 5


# 抽成函式, 讓 tasks_schedule.py 的定時任務也能共用同一段派工邏輯
def dispatch_pages():
    for page in range(TOTAL_PAGES):
        fetch_page.delay(page)


if __name__ == "__main__":
    dispatch_pages()
