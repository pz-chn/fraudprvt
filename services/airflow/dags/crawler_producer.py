# crawler_producer
# 由 Airflow 定時把派工任務送進 crawler 的 RabbitMQ, 取代 crawler_beat 的角色
# Airflow 只負責「到點送出任務」; 真正抓資料、寫 MySQL 的仍是 crawler_worker
import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.operators.python import PythonOperator

# 與 crawler/worker.py 的 app.conf.timezone 相同, cron 的時間以台北時間解讀
TAIPEI_TZ = pendulum.timezone("Asia/Taipei")

# crawler_worker 沒有指定 -Q, 也沒有設定 task_default_queue / task_routes,
# 所以它監聽的是 Celery 預設的 queue「celery」; 送任務時明確指定同一個 queue
CRAWLER_QUEUE = "celery"

default_args = {
    "owner": "fraudprvt",
    # 送任務失敗 (例如 RabbitMQ 剛好在重啟) 時, 隔 5 分鐘再試, 最多 2 次
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def send_crawler_task(task_name, args=None):
    # 在任務「執行時」才讀環境變數, Airflow 解析 DAG 檔時不需要這個變數
    broker_url = os.environ["CRAWLER_BROKER_URL"]

    # 放在函式裡 import: Celery 只有執行任務時才用得到, 也讓 DAG 解析更快
    from celery import Celery

    # 只用來送訊息的 Celery 客戶端, 不需要 import crawler 的程式碼
    with Celery(broker=broker_url) as app:
        # send_task 用「任務名稱字串」送出, 名稱必須與 worker 註冊的完全一致
        result = app.send_task(task_name, args=args or [], queue=CRAWLER_QUEUE)

    # 回傳 Celery task id, 會存進 XCom, 方便之後對照 worker 的 log
    return result.id


# 03:00 派工抓取 MyGoPen, 對應 beat 的 crawl-mygopen-daily
with DAG(
    dag_id="crawler_crawl_mygopen",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz=TAIPEI_TZ),
    catchup=False,  # 不補跑 start_date 以來錯過的日子
    max_active_runs=1,  # 同一時間只跑一個 DAG run
    default_args=default_args,
    tags=["crawler"],
):
    PythonOperator(
        task_id="send_crawl_mygopen",
        python_callable=send_crawler_task,
        op_kwargs={"task_name": "crawler.tasks_schedule.crawl_mygopen"},
    )


# 03:30 派工抓取 165 最後 3 頁, 對應 beat 的 crawl-165-recent-daily (args=(3,))
with DAG(
    dag_id="crawler_crawl_165_recent",
    schedule="30 3 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz=TAIPEI_TZ),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["crawler"],
):
    PythonOperator(
        task_id="send_crawl_165_recent",
        python_callable=send_crawler_task,
        op_kwargs={"task_name": "crawler.tasks_schedule.crawl_165_recent", "args": [3]},
    )
