# tasks_line
# 每天由 Airflow 觸發: 從 fraud_cases 取還沒發過的最新一則案例, 用 LINE broadcast 發給所有好友
# 165 週六日不更新, 平日也可能沒有新案例; 沒有新案例時改發還沒發過的較舊案例, 不會重複發同一則
from crawler.worker import app

from datetime import datetime, timedelta, timezone

import requests
from loguru import logger
from sqlalchemy import text

from crawler.config import LINE_CHANNEL_ACCESS_TOKEN
from crawler.tasks_165 import get_engine

BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"
CASE_PAGE_URL = "https://165dashboard.tw/city-case-summary"
REQUEST_TIMEOUT = 30

# LINE 一則文字訊息上限 5000 字, summary 先截斷, 留空間給標題與連結
MAX_SUMMARY_LENGTH = 4500

TAIPEI_TZ = timezone(timedelta(hours=8))

# 還沒發過的案例中, 日期最新、同一天 id 最大的那一則
# id 是 165 的來源編號, 實測同一天內連續遞增, 日期越新 id 越大
# 有新日期 → 發新日期 id 最大的; 沒有新日期 → 同一天往回找沒發過的; 同一天都發過 → 往前一天找
NEXT_CASE_SQL = text("""
    select c.id, c.case_date, c.case_title, c.summary
    from fraud_cases c
    left join line_case_pushes p on p.case_id = c.id
    where p.case_id is null
    order by c.case_date desc, c.id desc
    limit 1
""")

INSERT_PUSH_SQL = text("""
    insert into line_case_pushes (case_id, case_date, pushed_at)
    values (:case_id, :case_date, :pushed_at)
""")


def build_message(case):
    summary = (case.summary or "")[:MAX_SUMMARY_LENGTH]
    return (
        f"165 每日詐騙案例（{case.case_date}）\n"
        f"{case.case_title}\n\n"
        f"{summary}\n\n"
        f"更多案例：{CASE_PAGE_URL}"
    )


def broadcast(message):
    # 發給所有加好友的人; 會計入官方帳號每月的訊息額度 (依收到的人數計算)
    response = requests.post(
        BROADCAST_URL,
        headers={"Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"},
        json={"messages": [{"type": "text", "text": message}]},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()


@app.task()
def push_daily_case():
    if not LINE_CHANNEL_ACCESS_TOKEN:
        raise RuntimeError("沒有設定 LINE_CHANNEL_ACCESS_TOKEN")

    engine = get_engine()
    # 寫紀錄與發送包在同一個交易裡: 發送失敗會 rollback, 下次排程還會再發
    with engine.begin() as conn:
        case = conn.execute(NEXT_CASE_SQL).first()
        if case is None:
            logger.info("沒有還沒發過的案例, 不發送")
            return None

        conn.execute(INSERT_PUSH_SQL, {
            "case_id": case.id,
            "case_date": case.case_date,
            "pushed_at": datetime.now(TAIPEI_TZ).replace(tzinfo=None),
        })
        broadcast(build_message(case))

    logger.info(f"已發送案例 {case.id} ({case.case_date})")
    return case.id
