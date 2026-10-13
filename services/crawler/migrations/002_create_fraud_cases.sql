-- 002_create_fraud_cases.sql
-- 165 打詐儀錶板的案例摘要
-- 來源: POST https://165dashboard.tw/CIB_DWS_API/api/CaseSummary/GetCaseSummaryList
--
-- 執行方式：
--   docker exec -i crawler-mysql-1 mysql --default-character-set=utf8mb4 \
--     -uroot -p"$MYSQL_PASSWORD" test_mygopen < migrations/002_create_fraud_cases.sql

-- 不與 mygopen_articles 共用一張表：
-- mygopen 是「有作者、有查核結論、可被更新的公開文章」, 業務主鍵是 url;
-- 這裡是「民眾受害的行政紀錄, 寫入後不會變」, 主鍵是來源 Id。
-- 兩者欄位幾乎不重疊, 合併會讓 99.9% 的列有一半欄位是 NULL。
-- 要一起做全文搜尋時用 view 處理, 不要動基礎表。
CREATE TABLE IF NOT EXISTS fraud_cases (
  -- 來源 Id 是 18 位數字, 實測最大 3.6e17, 遠低於 BIGINT UNSIGNED 上限
  id         BIGINT UNSIGNED NOT NULL,
  -- 來源給的是 UTC (例如 2024-11-29T16:00:00Z 代表台北時間 2024-11-30),
  -- 寫入前必須做時區轉換再取日期, 直接截斷字串會讓整批日期往前偏一天
  case_date  DATE NOT NULL,
  city_id    SMALLINT NOT NULL,
  city_name  VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  -- 詐騙手法, 實測最長 42 字。前 20 名涵蓋 85% 的資料,
  -- 但有少數列其實是文章標題而非手法分類, 做 top-N 排行不受影響
  case_title VARCHAR(60) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  -- 當事人第一人稱敘述, 中位數 237 字, 實測最長 3269 字
  summary    TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (id),
  KEY idx_case_date (case_date),
  KEY idx_case_title (case_title),
  KEY idx_city_date (city_id, case_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
