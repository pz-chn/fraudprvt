-- 005_create_line_case_pushes.sql
-- 每天 19:00 用 LINE 推播的 165 案例紀錄, 用來避免同一則案例重複發送
--
-- 全新環境不需要執行: db/schema.sql 已包含這張表, MySQL 第一次初始化時會自動建立。
-- 只有「已經初始化過的現有資料庫」才需要手動執行這支 migration, 再補上 GRANT。
--
-- 執行方式 (在 repo 根目錄; root 密碼直接用 mysql 容器內的環境變數, 不用自己輸入):
--   docker exec -i $(docker ps -q -f name=fraudprvt_mysql) sh -c \
--     'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' \
--     < services/crawler/migrations/005_create_line_case_pushes.sql
--
-- 接著補權限 (與 db/init-users.sh 相同):
--   docker exec $(docker ps -q -f name=fraudprvt_mysql) sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "
--     GRANT SELECT, INSERT ON $MYSQL_DATABASE.line_case_pushes TO $CRAWLER_DB_ACCOUNT;"'

-- 165 週六日不更新, 平日也可能沒有新案例;
-- 推播時從 fraud_cases 挑「不在這張表裡」的案例中最新的一則
CREATE TABLE IF NOT EXISTS line_case_pushes (
  -- fraud_cases.id; 不設外鍵, 這張表只是發送紀錄
  case_id    BIGINT UNSIGNED NOT NULL,
  case_date  DATE NOT NULL,
  -- 台北時間
  pushed_at  DATETIME NOT NULL,
  PRIMARY KEY (case_id),
  KEY idx_case_date (case_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
