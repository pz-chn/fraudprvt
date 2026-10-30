# 匯入相關套件
import pandas as pd  # 用來處理資料表，把 SQL 查詢結果轉成 DataFrame
from fastapi import FastAPI, HTTPException, Request  # 加了 HTTPException回傳error給對方, Request讀進來的請求
from linebot.v3 import WebhookParser # 拆解line送來的資料
from linebot.v3.exceptions import InvalidSignatureError # 簽章驗證失敗時的error
from linebot.v3.messaging import ( # 回復訊息用的工具們
    ApiClient,
    Configuration,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent # 事件類型
from sqlalchemy import create_engine, engine, text  # 建立 DB 連線與引擎

# 匯入自定義的資料庫連線設定（從 config.py 來）
from api.config import (
    LINE_CHANNEL_ACCESS_TOKEN,
    LINE_CHANNEL_SECRET,
    MYSQL_ACCOUNT,
    MYSQL_DATABASE,
    MYSQL_HOST,
    MYSQL_PASSWORD,
    MYSQL_PORT,
)


# 建立 SQLAlchemy 引擎（管理連線池）
# 寫在檔案最外層：main.py 載入時只建立一次，之後所有請求共用同一個引擎
# 連線字串格式：mysql+pymysql://帳號:密碼@host:port/資料庫名
# mysql+pymysql 表示用 SQLAlchemy 介面 + PyMySQL 當底層 driver
db_engine = create_engine(
    f"mysql+pymysql://{MYSQL_ACCOUNT}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}",
    pool_pre_ping=True,  # 借出連線前先確認還活著，避免拿到被 MySQL 斷掉的閒置連線
)


# 從引擎借一條連線，回傳 SQLAlchemy 的連線物件
# 抽成函式的好處：每個 API 路由都可以呼叫，不用重複寫連線的細節
def get_mysql_fraudprvtdata_conn() -> engine.base.Connection:
    return db_engine.connect()  # 用完 close（或離開 with）時，連線會還回連線池


# 建立 FastAPI 應用實例
# 這個 app 物件就是整個 API 的核心，後面所有路由都註冊在它身上
# uvicorn 啟動時會找這個變數：uvicorn api.main:app 中的 :app 就是指這個
app = FastAPI()


# 定義根目錄路由（測試用）
# @app.get("/") 是 decorator，把下面這個函式註冊成「GET / 的處理器」，有人用 GET 打 / 時，執行這個函式
# 開瀏覽器打 http://localhost:8889/ 就會執行下面的 read_root()
@app.get("/")
def read_root():
    return {"Hello": "World"}  # FastAPI 會自動把 dict 轉成 JSON 回傳


# 定義從資料庫取得資料的 API 路由
# 函式參數會自動對應到 URL 的 query string (查詢字串)
# 例如 /fraud_prvt?dscp=熱水
# dscp="" 表示沒帶就預設空字串
@app.get("/fraud_prvt")
def fraud_prvt(
    dscp: str = "",  # 查詢字串（可透過 URL query string 傳入）
):
    # 分類儲存在 article_categories，用 group_concat 併回原本的逗號字串格式
    sql = text("""
    select
        a.id,
        a.title,
        a.verdict,
        a.published,
        a.url,
        a.content_text,
        group_concat(c.category order by c.category separator ', ') as categories
    from mygopen_articles a
    left join article_categories c on c.article_id = a.id
    where a.title like :kw or a.content_text like :kw
    group by a.id
    """)
    # 建立資料庫連線，離開 with 區塊時自動關閉（中途出錯也會關）
    with get_mysql_fraudprvtdata_conn() as mysql_conn:
        # 使用 Pandas 執行 SQL 查詢並取得資料
        # pd.read_sql 把查詢結果包成 DataFrame，省下手動 cursor.fetchall + 轉欄位
        data_df = pd.read_sql(sql, con=mysql_conn, params={"kw": f"%{dscp}%"})
    # 將 DataFrame 轉為 List of Dict 格式，方便 FastAPI 回傳 JSON
    # records 模式會產出 [{欄位:值, ...}, {欄位:值, ...}] 這種前端最愛吃的結構
    data_dict = data_df.to_dict("records")
    return {"data": data_dict}  # 回傳資料結果（FastAPI 自動序列化成 JSON）


def search_articles(keyword: str, limit: int = 5):
    # 用 :kw 這種參數寫法，% 放在參數值裡，不會再被格式化一次
    sql = text("""
        select title, published, url from mygopen_articles
        where title like :kw or content_text like :kw
        order by published desc
        limit :limit
    """)
    mysql_conn = get_mysql_fraudprvtdata_conn()
    try: # 如果try那邊error 最後會被 FastAPI 接住，回傳 500（伺服器錯誤）給 LINE
        rows = mysql_conn.execute(
            sql, {"kw": f"%{keyword}%", "limit": limit}
        ).fetchall() # 把結果全部拿回來，變成一個 list，每個元素是一列（Row 物件）
    finally: # 不管 try 有沒有出錯，都一定會執行
        mysql_conn.close()
    return rows


def build_reply(keyword: str) -> str:
    rows = search_articles(keyword)
    if not rows:
        return f"找不到和「{keyword}」相關的文章"
    items = []
    for i, r in enumerate(rows, 1):
        items.append(f"{i}. {r.title or '（無標題）'}\n發布時間：{r.published}\n{r.url}")
    header = f"找到和「{keyword}」相關的文章（最新 {len(rows)} 篇）："
    return (header + "\n\n" + "\n\n".join(items))[:4900]


line_config = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
line_parser = WebhookParser(LINE_CHANNEL_SECRET)


@app.post("/callback") #LINE 是「送資料過來」
async def callback(request: Request): #非同步函式 可以先理解成「這個函式裡面可以用 await 等待某些事情」 FastAPI 看到型別是 Request 就會把整個請求傳進來
    signature = request.headers.get("X-Line-Signature", "") #從請求的標頭（headers）讀出 LINE 附上的簽章 標頭就像信封外面寫的資訊，內容（body）是信封裡的信。沒有這個標頭就用空字串
    body = (await request.body()).decode("utf-8") #request.body() 讀出信的內容，因為要等資料傳完，所以前面要加 await。讀出來是 bytes（原始位元組），.decode("utf-8") 把它轉成一般文字
    try:
        events = line_parser.parse(body, signature) #line_parser.parse驗證是否是line來訊 如果是 存進events(json>>python物件list)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature") #如果try的驗證沒通過 回傳「400 錯誤：簽章無效」

    with ApiClient(line_config) as api_client: #建立跟 LINE 溝通的客戶端（帶著 access token），離開 with 時關閉
        line_api = MessagingApi(api_client) #MessagingApi 提供「發送訊息」相關的功能
        for event in events: #一次請求可能有多個事件，一個一個處理
            #兩個isinstance檢查 確認為文字訊息 (and的特性是 左邊是 False，右邊就不執行 所以這邊順序不能換)
            if isinstance(event, MessageEvent) and isinstance(
                event.message, TextMessageContent
            ):
                line_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token, #跟著每個使用者原文來的
                        messages=[TextMessage(text=build_reply(event.message.text.strip()))], #把使用者傳的原文去掉前後空白(strip) 從mysql組出回復內容 包成一則文字訊息 放進list
                    ) #把回給誰和回什麼內容包在一起
                ) #傳送給line
    return "OK" #回給line說ok(http200之意)