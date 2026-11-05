# crawler_producer
# 由 Airflow 定時把派工任務送進 RabbitMQ
# Airflow 只負責「送出」任務; 真正抓資料、寫 MySQL 的仍是 crawler_worker
import os # 讀環境變數用的
from datetime import timedelta # 讀一段時間長度用的 例如minutes=5、hours=2

import pendulum # 讀時區用的
from airflow import DAG # 建立排程用的
from airflow.operators.python import PythonOperator # 執行python函式用 要存參數

# 與 crawler/worker.py 的 app.conf.timezone 相同, cron 的時間以台北時間解讀
TAIPEI_TZ = pendulum.timezone("Asia/Taipei") # 把時區存進一個名稱叫 TAIPEI_TZ (常數 不會改)

# crawler_worker 沒有指定 -Q, 也沒有設定 task_default_queue / task_routes,
# 所以它監聽的是 Celery 預設的 queue「celery」; 送任務時明確指定同一個 queue
CRAWLER_QUEUE = "celery" # 預設的queue「celery」 worker也會從這個queue收任務

default_args = { # args=arguments參數
    "owner": "fraudprvt", # airflow上「owner」標籤
    # 送任務失敗 (例如 RabbitMQ 剛好在重啟) 時, 隔 5 分鐘再試, 最多 2 次
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}


def send_crawler_task(task_name, args=None): # 要送出紙條給 rabbitmq 的函式
    # 在任務「執行時」才讀環境變數, Airflow 解析 DAG 檔時不需要這個變數
    broker_url = os.environ["CRAWLER_BROKER_URL"]

    # 放在函式裡 import: Celery 只有執行任務時才用得到, 也讓 DAG 解析更快
    from celery import Celery # 傳遞任務用的

    # 只用來送訊息的 Celery 客戶端, 不需要 import crawler 的程式碼
    with Celery(broker=broker_url) as app:  # 開始送紙條給 rabbitmq 送完就關閉
        # send_task 用「任務名稱字串」送出, 名稱必須與 worker 註冊的完全一致
        result = app.send_task(task_name, args=args or [], queue=CRAWLER_QUEUE)  # 本py即將在每天固定時間送出的紙條

    # 回傳 Celery task id, 會存進 XCom, 方便之後對照 worker 的 log
    return result.id


# 03:00 派工抓取 MyGoPen
# with: 現在建立的事項都要放進這個 DAG
with DAG(
    dag_id="crawler_crawl_mygopen",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz=TAIPEI_TZ),
    catchup=False,  # 不補跑 start_date 以來錯過的日子
    max_active_runs=1,  # 同一時間只跑一個 DAG run
    default_args=default_args, # 上面18行那組代入這裡的dag參數
    tags=["crawler"], # airflow上的dag標籤
):
    PythonOperator( # 把要執行的參數先放這
        task_id="send_crawl_mygopen",
        python_callable=send_crawler_task,
        op_kwargs={"task_name": "crawler.tasks_schedule.crawl_mygopen"},
    )


# 03:30 派工抓取 165 最後 3 頁 (args=(3,))
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


# 03:00 派工抓取台灣事實查核中心 (TFC) 依修改時間排序的前 3 頁 (args=(3,))
# 與 MyGoPen 同時送出, crawler_worker 會從同一個 queue 輪流處理
with DAG(
    dag_id="crawler_crawl_tfc_recent",
    schedule="0 3 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz=TAIPEI_TZ),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["crawler"],
):
    PythonOperator(
        task_id="send_crawl_tfc_recent",
        python_callable=send_crawler_task,
        op_kwargs={"task_name": "crawler.tasks_schedule.crawl_tfc_recent", "args": [3]},
    )


# 19:00 用 LINE 推播最新一則 165 案例給所有好友
# 165 週六日不更新、平日也可能沒有新案例; 由 crawler_worker 比對發送紀錄, 挑還沒發過的最新一則
with DAG(
    dag_id="line_push_daily_case",
    schedule="0 19 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz=TAIPEI_TZ),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["line"],
):
    PythonOperator(
        task_id="send_push_daily_case",
        python_callable=send_crawler_task,
        op_kwargs={"task_name": "crawler.tasks_line.push_daily_case"},
    )
