# tasks_schedule
# 給 Celery Beat 定時觸發的派工任務
# 本身不抓資料, 只是把 producer 手動做的事改成由 beat 每天自動做一次
from crawler.worker import app

from crawler import producer, producer_165


@app.task()
def crawl_mygopen():
    # 與手動執行 producer.py 相同: 派送 page 0 ~ 4 的 fetch_page
    producer.dispatch_pages()


@app.task()
def crawl_165_recent(n=3):
    # 與 producer_165.py 帶參數 N 相同: 只派送最後 N 頁的 fetch_cases_page
    producer_165.dispatch_pages(n)
