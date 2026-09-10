import datetime
import logging
import pytz
import sqlite3
import os
from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, 'data.db')

app = Flask(__name__)


@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.ico')


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA busy_timeout=5000')
    conn.row_factory = sqlite3.Row
    return conn


def get_latest_reading():
    """获取最新的传感器读数"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM m1 ORDER BY id DESC LIMIT 1')
    row = cursor.fetchone()
    conn.close()
    return row


def get_config_value(key, default=None):
    """读取 config 表中的一项配置"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM config WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default


def set_config_value(key, value):
    """写入 config 表中的一项配置"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)',
        (key, str(value))
    )
    conn.commit()
    conn.close()


def get_current_brightness():
    """获取当前亮度设置"""
    value = get_config_value('brightness', '50')
    return int(value)


def is_brightness_auto():
    """是否处于自动亮度模式"""
    return get_config_value('brightness_auto', '0') == '1'


def get_retention_days():
    """获取数据保留天数"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'retention_days'")
    row = cursor.fetchone()
    conn.close()
    return int(row['value']) if row else 7


@app.route('/')
def index():
    row = get_latest_reading()
    if row is None:
        return render_template('index.html',
            info_time='--',
            info_humidity='--',
            info_temperature='--',
            info_pm25='--',
            info_hcho='--',
            info_brightness=50,
            info_brightness_auto=False)

    return render_template('index.html',
        info_time=timestamp2string(row['time']),
        info_humidity=row['humidity'],
        info_temperature=row['temperature'],
        info_pm25=row['pm25'],
        info_hcho=row['hcho'],
        info_brightness=get_current_brightness(),
        info_brightness_auto=is_brightness_auto())


@app.route('/getdata')
def getdata():
    row = get_latest_reading()
    if row is None:
        return jsonify(
            info_time='--',
            info_humidity='--',
            info_temperature='--',
            info_pm25='--',
            info_hcho='--',
            success=False
        )

    return jsonify(
        info_time=timestamp2string(row['time']),
        info_humidity=str(row['humidity']),
        info_temperature=str(row['temperature']),
        info_pm25=str(row['pm25']),
        info_hcho=str(row['hcho']),
        success=True
    )


@app.route('/api/history')
def api_history():
    """获取历史数据
    参数: hours - 查询最近N小时的数据, 默认24
    """
    try:
        hours = request.args.get('hours', 24, type=int)
    except (ValueError, TypeError):
        hours = 24
    if hours < 1:
        hours = 24
    # 限制最大查询范围,防止异常大值触发全表聚合
    if hours > 720:
        hours = 720

    now = int(datetime.datetime.now().timestamp())
    since = now - (hours * 3600)

    # 降采样：按时间范围选择聚合桶大小，避免一次返回过多数据
    if hours <= 6:
        bucket = 60      # 1~6小时: 1分钟/点，最多360点
    elif hours <= 24:
        bucket = 300     # 24小时: 5分钟/点，约288点
    elif hours <= 72:
        bucket = 300     # 3天: 5分钟/点，约864点
    else:
        bucket = 1200    # 7天: 20分钟/点，约504点

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        '''SELECT (time / ?) * ? AS bucket_time,
                  AVG(humidity) AS humidity,
                  AVG(temperature) AS temperature,
                  AVG(pm25) AS pm25,
                  AVG(hcho) AS hcho
           FROM m1
           WHERE time >= ?
           GROUP BY bucket_time
           ORDER BY bucket_time ASC''',
        (bucket, bucket, since)
    )
    rows = cursor.fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append({
            'time': row['bucket_time'],
            'time_str': timestamp2string(row['bucket_time']),
            'humidity': round(row['humidity'], 1),
            'temperature': round(row['temperature'], 1),
            'pm25': round(row['pm25'], 1),
            'hcho': round(row['hcho'], 2),
        })

    return jsonify(success=True, count=len(data), data=data)


@app.route('/api/brightness', methods=['GET'])
def api_brightness_get():
    """获取当前亮度和自动模式状态"""
    return jsonify(success=True,
                   brightness=get_current_brightness(),
                   auto=is_brightness_auto())


@app.route('/api/brightness', methods=['POST'])
def api_brightness_post():
    """设置亮度
    请求体: {"value": 50} 或 {"value": "auto"}
    固定档位: 0 (关), 25 (暗), 50 (标准); 选择固定档位即退出自动模式
    "auto": 启用自动模式(北京时间 21:00 切暗, 06:00 切标准)
    """
    data = request.get_json(force=True)
    value = data.get('value', 50)

    if value == 'auto':
        set_config_value('brightness_auto', '1')
        return jsonify(success=True, auto=True, brightness=get_current_brightness())

    if value not in (0, 25, 50):
        return jsonify(success=False, error='Invalid brightness value. Must be 0, 25, 50, or "auto".'), 400

    # 选择固定档位:写入亮度并关闭自动模式
    set_config_value('brightness', value)
    set_config_value('brightness_auto', '0')

    return jsonify(success=True, auto=False, brightness=value)


@app.route('/api/config', methods=['GET'])
def api_config_get():
    """获取系统配置"""
    brightness = get_current_brightness()
    retention_days = get_retention_days()
    return jsonify(success=True, brightness=brightness, retention_days=retention_days)


@app.route('/api/config', methods=['POST'])
def api_config_post():
    """更新系统配置
    请求体: {"retention_days": 7}
    """
    data = request.get_json(force=True)
    updates = []

    if 'retention_days' in data:
        days = data['retention_days']
        if not isinstance(days, int) or days < 1 or days > 365:
            return jsonify(success=False, error='retention_days must be an integer between 1 and 365.'), 400
        updates.append(('retention_days', str(days)))

    if 'brightness' in data:
        value = data['brightness']
        if value not in (0, 25, 50):
            return jsonify(success=False, error='brightness must be 0, 25, or 50.'), 400
        updates.append(('brightness', str(value)))

    if not updates:
        return jsonify(success=False, error='No valid config keys provided.'), 400

    conn = get_db()
    cursor = conn.cursor()
    for key, value in updates:
        cursor.execute(
            "INSERT OR REPLACE INTO config(key, value) VALUES(?, ?)",
            (key, value)
        )
    conn.commit()
    conn.close()

    return jsonify(success=True)


@app.route('/api/health')
def api_health():
    """健康检查端点"""
    try:
        conn = get_db()
        conn.execute('SELECT 1')
        conn.close()
        return jsonify(status='healthy', database='ok')
    except Exception as e:
        return jsonify(status='unhealthy', error=str(e)), 500


def timestamp2string(timestamp):
    _local_zone = pytz.timezone('Asia/Shanghai')
    d = datetime.datetime.fromtimestamp(timestamp, _local_zone)
    return d.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == '__main__':
    # 前端每5秒轮询 /getdata, 关闭 werkzeug 每请求访问日志, 防止容器 stdout 日志无限增长
    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    app.run(debug=False, host='0.0.0.0', port=5000)