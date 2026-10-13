-- 003_trim_fraud_case_text.sql
-- 清掉 fraud_cases 文字欄位前後的空白字元
--
-- 來源 API 的 CaseTitle 有 113 種帶著換行或 tab, 例如 '\n \t\n騙取金融帳戶(卡片)詐騙'。
-- MySQL 的 PAD SPACE collation 只忽略尾端「空格」, 換行與 tab 不會被忽略,
-- 所以這些值在 GROUP BY 時會各自成為一個 bucket, 看起來像重複的分類。
-- 實測影響 case_title 1639 列、summary 8279 列。
--
-- 爬蟲端 (crawler/tasks_165.py 的 clean_text) 已經會在寫入前 strip,
-- 這支只是把回補時就已經寫進去的既有資料補正, 不必重爬 198 頁。
-- 用 REGEXP_REPLACE 是冪等的, 重跑無害。
--
-- 執行方式：
--   docker exec -i crawler-mysql-1 mysql --default-character-set=utf8mb4 \
--     -uroot -p"$MYSQL_PASSWORD" test_mygopen < migrations/003_trim_fraud_case_text.sql

UPDATE fraud_cases
SET case_title = REGEXP_REPLACE(case_title, '^[[:space:]]+|[[:space:]]+$', ''),
    city_name  = REGEXP_REPLACE(city_name,  '^[[:space:]]+|[[:space:]]+$', ''),
    summary    = REGEXP_REPLACE(summary,    '^[[:space:]]+|[[:space:]]+$', '');
