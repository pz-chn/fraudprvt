#!/bin/bash
# 建立各服務專用的資料庫帳號與權限 (API 唯讀、crawler 寫入、airflow 專屬資料庫)。
# 此腳本只在 MySQL 資料目錄為空時 (第一次初始化) 由 mysql image 的 entrypoint 執行一次,
# 之後重啟容器不會再跑。
# 所有帳號密碼都來自環境變數 (由 stack.yml 傳入), 腳本內不寫死任何密碼。
# 注意: 新增資料表時, 要在這裡手動補上對應的 GRANT;
#       已經初始化過的現有資料庫不會重跑此腳本, 需另外手動執行 GRANT。
set -euo pipefail

MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot <<SQL
CREATE USER '${API_DB_ACCOUNT}'@'%' IDENTIFIED BY '${API_DB_PASSWORD}';
GRANT SELECT ON ${MYSQL_DATABASE}.mygopen_articles TO '${API_DB_ACCOUNT}'@'%';
GRANT SELECT ON ${MYSQL_DATABASE}.article_categories TO '${API_DB_ACCOUNT}'@'%';

CREATE USER '${CRAWLER_DB_ACCOUNT}'@'%' IDENTIFIED BY '${CRAWLER_DB_PASSWORD}';
GRANT SELECT, INSERT, UPDATE ON ${MYSQL_DATABASE}.mygopen_articles TO '${CRAWLER_DB_ACCOUNT}'@'%';
GRANT SELECT, INSERT, DELETE ON ${MYSQL_DATABASE}.article_categories TO '${CRAWLER_DB_ACCOUNT}'@'%';
GRANT SELECT, INSERT, UPDATE ON ${MYSQL_DATABASE}.fraud_cases TO '${CRAWLER_DB_ACCOUNT}'@'%';

CREATE DATABASE airflow CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '${AIRFLOW_DB_ACCOUNT}'@'%' IDENTIFIED BY '${AIRFLOW_DB_PASSWORD}';
GRANT ALL PRIVILEGES ON airflow.* TO '${AIRFLOW_DB_ACCOUNT}'@'%';
SQL
