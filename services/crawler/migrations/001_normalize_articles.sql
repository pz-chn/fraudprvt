-- 001_normalize_articles.sql
-- 把 mygopen_articles 從「全部欄位都是 TEXT」改成可做聚合查詢的結構
--
-- 這支 migration 不可重複執行（MySQL 的 ADD COLUMN 不支援 IF NOT EXISTS）
-- 執行方式：
--   docker exec -i crawler-mysql-1 mysql --default-character-set=utf8mb4 \
--     -uroot -p"$MYSQL_PASSWORD" test_mygopen < migrations/001_normalize_articles.sql

-- ---------------------------------------------------------------
-- Step 1. 備份原表（DDL 在 MySQL 無法 rollback，所以備份是唯一的退路）
-- ---------------------------------------------------------------
CREATE TABLE mygopen_articles_backup_20261003 AS
SELECT * FROM mygopen_articles;


-- ---------------------------------------------------------------
-- Step 2. 調整欄位型別，並新增 verdict 與暫時的 published_dt
--         TEXT 改成 VARCHAR 才能建索引；url 設 NOT NULL 因為它是業務主鍵
--
--         url 一定要用 utf8mb4_bin：表的預設 collation utf8mb4_unicode_ci
--         不分大小寫，但網址的 path 本來就區分大小寫。實際資料裡
--         venezuela.html 與 Venezuela.html 是兩篇不同的文章，
--         用 ci collation 會讓 Step 5 的 UNIQUE KEY 誤判成衝突，
--         爬蟲端的 upsert 也會讓其中一篇覆蓋掉另一篇
-- ---------------------------------------------------------------
ALTER TABLE mygopen_articles
  MODIFY COLUMN title VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci,
  MODIFY COLUMN url   VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  ADD    COLUMN verdict      VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NULL AFTER title,
  ADD    COLUMN published_dt DATETIME NULL AFTER published;


-- ---------------------------------------------------------------
-- Step 3. 回填資料
-- ---------------------------------------------------------------

-- 3a. published: '2026-08-22T11:00:53.497+08:00' -> DATETIME
--     前 19 字元就是 'YYYY-MM-DDTHH:MM:SS'，剛好切掉毫秒與時區
--     原值的 +08:00 已是台北時間，直接截斷等同存成 naive 台北時間，
--     與爬蟲端 tz_localize(None) 的行為一致
UPDATE mygopen_articles
SET published_dt = STR_TO_DATE(SUBSTRING(published, 1, 19), '%Y-%m-%dT%H:%i:%s')
WHERE published IS NOT NULL;

-- 3b. verdict: 從標題的 '【錯誤】xxx' 取出 '錯誤'
UPDATE mygopen_articles
SET verdict = SUBSTRING_INDEX(SUBSTRING_INDEX(title, '】', 1), '【', -1)
WHERE title LIKE '【%】%';


-- ---------------------------------------------------------------
-- Step 4. 用 published_dt 取代原本的 published
--         沿用 published 這個欄位名，API 端現有查詢才不用改
-- ---------------------------------------------------------------
ALTER TABLE mygopen_articles DROP COLUMN published;

ALTER TABLE mygopen_articles
  CHANGE COLUMN published_dt published DATETIME NULL;


-- ---------------------------------------------------------------
-- Step 5. 建立索引
--         視覺化的查詢幾乎都是「依時間篩選 + 依 verdict 分組」
-- ---------------------------------------------------------------
ALTER TABLE mygopen_articles
  ADD UNIQUE KEY uk_url (url),
  ADD KEY idx_published (published),
  ADD KEY idx_verdict (verdict);


-- ---------------------------------------------------------------
-- Step 6. 分類改成一對多的橋接表
--         原本 'AI, 假影片, 挪威' 塞在一個欄位，無法 GROUP BY
-- ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS article_categories (
  article_id INT NOT NULL,
  category   VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (article_id, category),
  KEY idx_category (category),
  CONSTRAINT fk_article_categories_article
    FOREIGN KEY (article_id) REFERENCES mygopen_articles (id)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 用 recursive CTE 把逗號字串逐段切開
-- 每次遞迴取出第一段當 category，剩下的字串放回 rest 繼續切
INSERT INTO article_categories (article_id, category)
WITH RECURSIVE split AS (
  SELECT
    id AS article_id,
    TRIM(SUBSTRING_INDEX(categories, ',', 1)) AS category,
    CASE WHEN LOCATE(',', categories) > 0
         THEN SUBSTRING(categories, LOCATE(',', categories) + 1)
         ELSE NULL
    END AS rest
  FROM mygopen_articles
  WHERE categories IS NOT NULL AND categories <> ''

  UNION ALL

  SELECT
    article_id,
    TRIM(SUBSTRING_INDEX(rest, ',', 1)),
    CASE WHEN LOCATE(',', rest) > 0
         THEN SUBSTRING(rest, LOCATE(',', rest) + 1)
         ELSE NULL
    END
  FROM split
  WHERE rest IS NOT NULL
)
SELECT DISTINCT article_id, category
FROM split
WHERE category <> '';


-- ---------------------------------------------------------------
-- Step 7. 移除已被橋接表取代的 categories 欄位
--         （備份表裡還留著原始字串）
-- ---------------------------------------------------------------
ALTER TABLE mygopen_articles DROP COLUMN categories;
