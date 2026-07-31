import socket
import threading
import time
import sys
import json
import re
import sqlite3
import datetime
import logging
import os

# SQLite数据库文件路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'data.db')
# 是否写入到SQLite数据库,True写入,False不写入
isSql = True
# 每隔多少获取信息,并写入SQLite数据中,单位秒
time_sleep = 5
# 数据保留天数(默认7天)
DEFAULT_RETENTION_DAYS = 7

# 全局亮度状态(0=关, 25=暗, 50=标准)
_brightness = 50
_brightness_lock = threading.Lock()


def get_db():
    """获取数据库连接,启用WAL模式以支持并发读写"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """初始化数据库,创建所需表结构"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS m1(
            id integer primary key autoincrement,
            time integer,
            humidity real,
            temperature real,
            pm25 real,
            hcho real
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS config(
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')

    # 设置默认配置
    defaults = {
        'brightness': '50',
        'retention_days': str(DEFAULT_RETENTION_DAYS),
    }
    for key, value in defaults.items():
        cursor.execute('SELECT COUNT(*) FROM config WHERE key = ?', (key,))
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO config(key, value) VALUES(?, ?)', (key, value))

    conn.commit()
    conn.close()
    _log('Database initialized successfully.', 0)


def load_brightness():
    """从数据库加载当前亮度设置"""
    global _brightness
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'brightness'")
        row = cursor.fetchone()
        if row:
            with _brightness_lock:
                _brightness = int(row['value'])
        conn.close()
    except Exception as e:
        _log(f'Failed to load brightness: {e}', 2)


def get_brightness():
    """获取当前亮度值"""
    with _brightness_lock:
        return _brightness


def cleanup_old_data():
    """清理过期的历史数据"""
    try:
        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT value FROM config WHERE key = 'retention_days'")
        row = cursor.fetchone()
        days = int(row['value']) if row else DEFAULT_RETENTION_DAYS

        cutoff_time = int(time.time()) - (days * 86400)
        cursor.execute('DELETE FROM m1 WHERE time < ?', (cutoff_time,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()

        if deleted > 0:
            _log(f'Cleaned up {deleted} old records (older than {days} days).', 0)
    except Exception as e:
        _log(f'Failed to cleanup old data: {e}', 2)


def cleanup_scheduler():
    """定时清理线程,每小时执行一次"""
    _log('Cleanup scheduler started (runs every hour).', 3)
    while True:
        time.sleep(3600)
        cleanup_old_data()


def build_heartbeat_msg(brightness):
    """构建心跳消息,包含亮度控制
    亮度值: 0=关, 25=暗, 50=标准
    """
    return (
        b'\xaaO\x01\xf2E\x119\x8f\x0b\x00\x00\x00\x00\x00\x00\x00\x00\xb0\xf8\x93\x11T/\x007\x00\x00\x02'
        + f'{{"brightness":"{brightness}","type":2}}'.encode()
        + b'\xff#END#'
    )


def socket_service():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('0.0.0.0', 9000))
        s.listen(10)
    except socket.error as msg:
        _log(f'Socket bind failed: {msg}', 2)
        sys.exit(1)
    _log('Waiting connection on port 9000...', 0)

    while True:
        try:
            conn, addr = s.accept()
            _log(f'New connection from {addr}', 0)
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
        except Exception as e:
            _log(f'Accept error: {e}', 2)


def handle_client(conn, addr):
    """处理单个M1设备连接"""
    _log(f'Client thread started for {addr}', 3)
    # 设置socket超时,防止设备断开不发送FIN包时recv永久阻塞
    conn.settimeout(time_sleep * 2)
    try:
        while True:
            brightness = get_brightness()
            heartbeat = build_heartbeat_msg(brightness)
            conn.sendall(heartbeat)

            try:
                data = conn.recv(1024)
            except socket.timeout:
                _log(f'Client {addr} recv timeout', 1)
                break
            except ConnectionResetError:
                _log(f'Client {addr} connection reset', 1)
                break

            if not data:
                _log(f'Client {addr} disconnected', 1)
                break

            jsonData = parseJsonData(data)
            _log(f'Get M1 data: {jsonData}', 3)

            if jsonData is not None:
                print(jsonData)
                info_Humidity = cut(float(jsonData['humidity']), 1)
                info_Temperature = cut(float(jsonData['temperature']), 1)
                info_PM25 = jsonData['value']
                info_HCHO = cut(float(jsonData['hcho']) / 1000, 2)
                if isSql:
                    sqlite_insert(timestamp2(), info_Humidity, info_Temperature, info_PM25, info_HCHO)

            time.sleep(time_sleep)
    except Exception as e:
        _log(f'Client {addr} error: {e}', 2)
    finally:
        try:
            conn.close()
        except Exception:
            pass
        _log(f'Client {addr} disconnected.', 0)


def sqlite_insert(timestamp, humidity, temperature, pm25, hcho):
    """插入一条传感器数据"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute(
            'INSERT INTO m1(time, humidity, temperature, pm25, hcho) VALUES (?, ?, ?, ?, ?)',
            (timestamp, humidity, temperature, pm25, hcho)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        _log(f'SQLite insert failed: {e}', 2)


def parseJsonData(data):
    pattern = r"(\{.*?\})"
    jsonStr = re.findall(pattern, str(data), re.M)
    if len(jsonStr) > 0:
        return json.loads(jsonStr[-1])
    return None


def timestamp2():
    return int(time.time())


def timestamp2string(timeStamp):
    d = datetime.datetime.fromtimestamp(timeStamp)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def cut(num, c):
    str_num = str(num)
    return str(str_num[:str_num.index('.') + 1 + c])


def _log(str, level):
    logger = logging.getLogger('PhicommM1 Server')
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        ls = logging.StreamHandler()
        ls.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s : %(message)s')
        ls.setFormatter(formatter)
        logger.addHandler(ls)

        logdir = os.path.join(BASE_DIR, 'logs')
        if not os.path.exists(logdir):
            os.makedirs(logdir, exist_ok=True)
        logfile = os.path.join(logdir, time.strftime('%Y-%m-%d') + '.log')
        lf = logging.FileHandler(filename=logfile, encoding='utf8')
        lf.setLevel(logging.DEBUG)
        lf.setFormatter(formatter)
        logger.addHandler(lf)

    if level == 0:
        logger.info(str)
    elif level == 1:
        logger.warning(str)
    elif level == 2:
        logger.error(str)
    elif level == 3:
        logger.debug(str)


if __name__ == '__main__':
    _log('Starting Phicomm M1 Server...', 0)
    init_db()
    load_brightness()

    # 启动数据清理后台线程
    cleanup_thread = threading.Thread(target=cleanup_scheduler, daemon=True)
    cleanup_thread.start()

    socket_service()