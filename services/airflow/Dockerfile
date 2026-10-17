# 官方 Airflow 映像, 版本與課程範本的 apache-airflow==2.7.3 一致
FROM apache/airflow:2.7.3

# 官方映像不允許用 root 執行 pip install, 明確切回 airflow 使用者 (基底映像預設也是它)
USER airflow

# metadata DB 用 mysql+pymysql 連線, 官方映像沒有附 pymysql
# 同時把 apache-airflow 釘在 2.7.3, 避免 pip 解相依時順手升級 Airflow
# pymysql 釘在 1.1.1: 基底映像是 Python 3.8, 較新的版本不保證支援
RUN pip install --no-cache-dir "apache-airflow==2.7.3" "pymysql==1.1.1"

# 只放 DAG; airflow.cfg、.env、*.ini 都不進 image, 設定一律在部署時用環境變數注入
COPY dags/ /opt/airflow/dags/
