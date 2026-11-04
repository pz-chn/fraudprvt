-- 004_create_tfc_articles.sql
-- 台灣事實查核中心 (TFC) 的查核報告與報告類型
-- 來源: GET https://tfc-taiwan.org.tw/wp-json/wp/v2/fact-check-reports
--
-- 全新環境不需要執行: db/schema.sql 已包含這兩張表, MySQL 第一次初始化時會自動建立。
-- 只有「已經初始化過的現有資料庫」才需要手動執行這支 migration, 再補上 GRANT。
--
-- 執行方式 (在 repo 根目錄; root 密碼直接用 mysql 容器內的環境變數, 不用自己輸入):
--   docker exec -i $(docker ps -q -f name=fraudprvt_mysql) sh -c \
--     'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --default-character-set=utf8mb4 -uroot "$MYSQL_DATABASE"' \
--     < services/crawler/migrations/004_create_tfc_articles.sql
--
-- 接著補權限 (與 db/init-users.sh 相同; 帳號名稱同樣取自容器內的環境變數,
-- 不寫主機部分時 MySQL 視為 '帳號'@'%'):
--   docker exec $(docker ps -q -f name=fraudprvt_mysql) sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -e "
--     GRANT SELECT, INSERT, UPDATE ON $MYSQL_DATABASE.tfc_articles TO $CRAWLER_DB_ACCOUNT;
--     GRANT SELECT, INSERT, DELETE ON $MYSQL_DATABASE.tfc_article_categories TO $CRAWLER_DB_ACCOUNT;
--     GRANT SELECT ON $MYSQL_DATABASE.tfc_articles TO $API_DB_ACCOUNT;
--     GRANT SELECT ON $MYSQL_DATABASE.tfc_article_categories TO $API_DB_ACCOUNT;"'

-- 不與 mygopen_articles 共用一張表:
-- 兩個來源的欄位與更新方式不同 (TFC 有最後修改時間, 主鍵是來源編號),
-- 要一起搜尋時在查詢端合併, 不要動基礎表。

-- 主鍵用 TFC 自己的文章編號 (WordPress post id), 不用 url:
-- WordPress 的網址由 slug 產生, 編輯改了 slug 就會變, 用 url 判斷會多出重複的一篇
CREATE TABLE IF NOT EXISTS tfc_articles (
  source_id    INT UNSIGNED NOT NULL,
  title        VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  -- 錯誤 / 部分錯誤 / 事實釐清 / 證據不足 / 正確
  verdict      VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  -- 兩個時間都是台北時間、不帶時區, 與 mygopen_articles.published 一致
  published    DATETIME DEFAULT NULL,
  modified     DATETIME DEFAULT NULL,
  url          VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  content_text TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  PRIMARY KEY (source_id),
  KEY idx_verdict (verdict)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 報告類型 (生活 / 國際 / 健康 ...), 結構與 article_categories 相同
-- 外鍵指向 tfc_articles, 所以這張表要在 tfc_articles 之後建立
CREATE TABLE IF NOT EXISTS tfc_article_categories (
  article_id INT UNSIGNED NOT NULL,
  category   VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (article_id, category),
  KEY idx_category (category),
  CONSTRAINT fk_tfc_article_categories_article
    FOREIGN KEY (article_id) REFERENCES tfc_articles (source_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
