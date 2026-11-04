# tasks_schedule
# airflow 定時觸發的派工任務
# 本身不抓資料，給出更多紙條
from crawler.worker import app # 從worker.py拿出app

from crawler import producer, producer_165, producer_tfc # 讀producer.py、producer_165.py和producer_tfc.py


@app.task() # 把以下函式登記進app名冊 名字是crawler.tasks_schedule.crawl_mygopen 對應到dags傳來的紙條
def crawl_mygopen():
    # 與手動執行 producer.py 相同: 派送 page 0 ~ 4 的 fetch_page
    producer.dispatch_pages()


@app.task()
def crawl_165_recent(n=3):
    # 與 producer_165.py 帶參數 N 相同: 只派送最後 N 頁的 fetch_cases_page
    producer_165.dispatch_pages(n)


@app.task()
def crawl_tfc_recent(n=3):
    # 與 producer_tfc.py 帶參數 N 相同: 依修改時間排序, 只派送最前面 N 頁的 fetch_tfc_page
    producer_tfc.dispatch_pages(n)
