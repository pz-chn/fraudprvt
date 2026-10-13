# db_retry
# 兩個爬蟲任務共用的「資料庫錯誤要不要重試」判斷
import random

from sqlalchemy.exc import OperationalError

# 1213: 死鎖 (Deadlock found when trying to get lock)
# 1205: 等鎖逾時 (Lock wait timeout exceeded)
# 這兩種是交易被 InnoDB 撤銷, 整頁重跑一次通常就會成功; 其他錯誤重試也沒用
RETRYABLE_MYSQL_ERRORS = (1213, 1205)
MAX_DB_RETRIES = 5


def is_retryable_db_error(exc):
    if not isinstance(exc, OperationalError):
        return False
    args = getattr(exc.orig, "args", ())
    return bool(args) and args[0] in RETRYABLE_MYSQL_ERRORS


def retry_countdown(retries):
    # 指數退避, 上限 30 秒; 乘上隨機係數讓同時撞到死鎖的任務錯開重跑時間
    return min(2 ** retries, 30) * random.uniform(0.5, 1.5)
