import datetime
import pytz
import sqlite3
import os
from flask import Flask, jsonify, render_template, request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'data.db')

app = Flask(__name__)


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


def get_current_brightness():
    """获取当前亮度设置"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM config WHERE key = 'brightness'")
    row = cursor.fetchone()
    conn.close()
    return int(row['value']) if row else 50


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
            info_brightness=50)

    brightness = get_current_brightness()
    return render_template('index.html',
        info_time=timestamp2string(row['time']),
        info_humidity=row['humidity'],
        info_temperature=row['temperature'],
        info_pm25=row['pm25'],
        info_hcho=row['hcho'],
        info_brightness=brightness)


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

    since = int(datetime.datetime.now().timestamp()) - (hours * 3600)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'SELECT time, humidity, temperature, pm25, hcho FROM m1 WHERE time >= ? ORDER BY time ASC',
        (since,)
    )
    rows = cursor.fetchall()
    conn.close()

    data = []
    for row in rows:
        data.append({
            'time': row['time'],
            'time_str': timestamp2string(row['time']),
            'humidity': row['humidity'],
            'temperature': row['temperature'],
            'pm25': row['pm25'],
            'hcho': row['hcho'],
        })

    return jsonify(success=True, count=len(data), data=data)


@app.route('/api/brightness', methods=['GET'])
def api_brightness_get():
    """获取当前亮度"""
    brightness = get_current_brightness()
    return jsonify(success=True, brightness=brightness)


@app.route('/api/brightness', methods=['POST'])
def api_brightness_post():
    """设置亮度
    请求体: {"value": 50}
    有效值: 0 (关), 25 (暗), 50 (标准)
    """
    data = request.get_json(force=True)
    value = data.get('value', 50)

    if value not in (0, 25, 50):
        return jsonify(success=False, error='Invalid brightness value. Must be 0, 25, or 50.'), 400

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO config(key, value) VALUES('brightness', ?)",
        (str(value),)
    )
    conn.commit()
    conn.close()

    return jsonify(success=True, brightness=value)


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
    app.run(debug=False, host='0.0.0.0', port=5000)