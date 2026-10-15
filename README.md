# 詐騙文章查詢 LINE Bot （建置中）

平時多看詐騙案例有助避免被騙～
收集臺灣獲 IFCN 認證的 Taiwan FactCheck Center（台灣事實查核中心）和 MyGoPen 的查核文章，與臺灣內政部警政署的各縣市每日案例，存進 MySQL；提供以關鍵字查詢查核文章的功能，且每天主動傳送一則「每日案例」給使用者。

> 目前狀態：資料收集與每日自動更新已在本機 Docker Swarm 上運作；LINE 串接與雲端部署尚在進行。

## 這個專案做什麼

- 每天自動爬取 MyGoPen 最新查核文章，存入 `mygopen_articles`（含分類 `article_categories`）。
- 每天自動增量更新內政部警政署的各縣市每日案例，存入 `fraud_cases`（目前 API 尚未使用）。
- FastAPI 提供查詢介面，並預計以 LINE webhook 讓使用者在 LINE 傳關鍵字查詢。
- 截至 2026-10-13：`mygopen_articles` 154 筆、`fraud_cases` 198,750 筆。

## 資料來源

- MyGoPen 查核文章。
- 內政部警政署的各縣市每日案例。
- 資料與文章內容的權利屬各來源網站，本專案為學習用途。

## 架構與資料流

```
Celery Beat ──每日派工──▶ RabbitMQ ──▶ Celery worker ──▶ MySQL ◀── FastAPI ◀── LINE webhook / 瀏覽器
 (只負責到點派工)         (任務佇列)    (爬取並寫入)      (資料)   (查詢)
```

## 本機執行

需求：Docker Desktop，並啟用 Swarm。

```bash
git clone https://github.com/pz-chn/fraudprvt.git
cd fraudprvt

# 1. 設定環境變數（密碼請自行設定，勿使用任何範本或課堂提供的帳密）
cp .env.stack.example .env.stack     # 依欄位填寫
cp .env.line.example .env.line     # 填入 LINE 的 Channel secret 與 access token（不進 git）

# 2. 建置 image
docker build -t fraudprvt_api:local services/api
docker build -t fraudprvt_crawler:local services/crawler

# 3. 部署
docker swarm init                    # 若尚未啟用 Swarm
set -a; source .env.stack; source .env.line; set +a
docker stack deploy --resolve-image never -c stack.yml fraudprvt

# 4. 建立資料表（目前需手動執行，之後會改為自動）
docker exec -i $(docker ps -q -f name=fraudprvt_mysql) \
  sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot fraudprvt' < db/schema.sql

# 5. 手動觸發第一次爬取（之後由 Beat 每天自動執行）
docker exec $(docker ps -q -f name=fraudprvt_crawler_worker) \
  uv run celery -A crawler.worker call crawler.tasks_schedule.crawl_mygopen
```

注意：以上步驟尚未用乾淨的 clone 完整驗證過一遍。

## 專案結構

```
fraudprvt/
├── stack.yml                 # Swarm stack：五個服務的定義
├── db/schema.sql             # 資料表結構
├── .env.stack.example        # 部署用環境變數欄位（只有欄位名稱）
└── services/
    ├── api/                  # FastAPI（Dockerfile、pyproject.toml、api/）
    └── crawler/              # Celery 爬蟲（crawler/ 任務、migrations/、Dockerfile）
```

## 作者與來源

作者：pz-chn。本專案以 TibaMe 資料工程班的課程範本為起點延伸開發。
