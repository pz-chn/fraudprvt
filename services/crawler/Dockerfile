FROM python:3.11-slim

WORKDIR /app

# 安裝 uv 這個套件管理工具
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# 先複製套件清單, 安裝依賴 (這樣改程式碼時不用重新安裝套件, 加快 build 速度)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project

# 複製剩下的程式碼進去
COPY . .

# 預設啟動 worker; 如果要跑 producer, 可以在 docker run 時用其他指令覆蓋
CMD ["uv", "run", "celery", "-A", "crawler.worker", "worker", "--loglevel=info"]