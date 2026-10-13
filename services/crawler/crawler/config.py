# config
import os

WORKER_ACCOUNT = os.environ["WORKER_ACCOUNT"]
WORKER_PASSWORD = os.environ["WORKER_PASSWORD"]

RABBITMQ_HOST = os.environ["RABBITMQ_HOST"]
RABBITMQ_PORT = int(os.environ["RABBITMQ_PORT"])

# MySQL 連線設定, 用來把爬蟲結果寫進資料庫
MYSQL_HOST = os.environ["MYSQL_HOST"]
MYSQL_PORT = int(os.environ["MYSQL_PORT"])
MYSQL_ACCOUNT = os.environ["MYSQL_ACCOUNT"]
MYSQL_PASSWORD = os.environ["MYSQL_PASSWORD"]
MYSQL_DATABASE = os.environ["MYSQL_DATABASE"]
