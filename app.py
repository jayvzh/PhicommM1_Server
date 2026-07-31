import datetime
import pytz
import sqlite3
import os
from flask import Flask, jsonify, render_template, url_for

# SQLite数据库文件路径
SQLITE_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.db')

app = Flask(__name__)


@app.route('/')
def index():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('select * from m1 order by id DESC')
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    
    return render_template(
        'index.html',
        info_time=timestamp2string(row['time']),
        info_humidity=row['humidity'],
        info_temperature=row['temperature'],
        info_pm25=row['pm25'],
        info_hcho=row['hcho']
    )


@app.route('/getdata')
def getdata():
    conn = sqlite3.connect(SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('select * from m1 order by id DESC')
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    
    info_time = timestamp2string(row['time'])
    info_humidity = str(row['humidity'])
    info_temperature = str(row['temperature'])
    info_pm25 = str(row['pm25'])
    info_hcho = str(row['hcho'])
    return jsonify(
        info_time=info_time,
        info_humidity=info_humidity,
        info_temperature=info_temperature,
        info_pm25=info_pm25,
        info_hcho=info_hcho
    )


# 时间戳转为文本时间格式
def timestamp2string(timestamp):
    _local_zone = pytz.timezone('Asia/Shanghai')
    d = datetime.datetime.fromtimestamp(timestamp, _local_zone)
    str1 = d.strftime("%Y-%m-%d %H:%M:%S")
    # 2022-06-29 16:43:37'
    return str1


# Json处理从M1取得的数据
def parsejsondata(data):
    pattern = r"(\{.*?\})"
    jsonstr = re.findall(pattern, str(data), re.M)
    l = len(jsonstr)
    if l > 0:
        return json.loads(jsonstr[l - 1])
    else:
        return None


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0', port=5000)
