# db_retry
# 兩個爬蟲任務共用的「資料庫錯誤要不要重試」判斷
import random #產生隨機數用

from sqlalchemy.exc import OperationalError #錯誤(exception)類型:執行時的狀況的問題

# 1213: 死鎖 (Deadlock found when trying to get lock)
# 1205: 等鎖逾時 (Lock wait timeout exceeded)
# 這兩種是交易被 InnoDB(MySQL 預設使用的儲存引擎)撤銷, 整頁重跑一次通常就會成功; 其他錯誤重試也沒用(例如SQL 寫錯、欄位名稱不對這類錯誤重試100次還是錯)
RETRYABLE_MYSQL_ERRORS = (1213, 1205) #全大寫 常數
MAX_DB_RETRIES = 5


def is_retryable_db_error(exc): #is開頭 表示要回傳true或false
    if not isinstance(exc, OperationalError): #isinstance用來問「這個東西是不是這個類型」
        return False
    args = getattr(exc.orig, "args", ()) #取得這個物件(exc.orig)的屬性名("args")，沒有就用預設值(())
    return bool(args) and args[0] in RETRYABLE_MYSQL_ERRORS #bool(args)有東西true 空的false; args[0]是exc.orig(PyMySQL原始錯誤)的第一個值=錯誤碼(例如1213) 檢查args[0]是否在(1213, 1205)裡面; and如果左邊false右邊就不會執行


def retry_countdown(retries):
    # 指數退避, 上限 30 秒; 乘上隨機係數讓同時撞到死鎖的任務錯開重跑時間
    return min(2 ** retries, 30) * random.uniform(0.5, 1.5)
