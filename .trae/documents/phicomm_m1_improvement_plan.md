# Phicomm M1 Server 改进计划

## 项目现状分析

### 当前架构
- `PhicommM1Server.py`: TCP服务端(端口9000)，监听M1设备数据，写入SQLite
- `app.py`: Flask Web服务(端口5000)，提供前端页面和API
- `templates/index.html`: 前端展示页，内存中仅保留最近12条数据做图表
- SQLite `data.db`: 单表 `m1`(id, time, humidity, temperature, pm25, hcho)

### 已发现问题
| # | 文件 | 问题 | 影响 |
|---|------|------|------|
| 1 | `PhicommM1Server.py:68-88` | `sqlite_conn()` 异常时无返回值，`sqlite_insert()` 解包报错 | 运行时崩溃 |
| 2 | `app.py:20-21` | 数据库为空时 `fetchone()` 返回 None，字段访问 TypeError | 首次部署白屏 |
| 3 | `PhicommM1Server.py` | 无历史数据清理机制，数据库无限增长 | 磁盘爆满风险 |
| 4 | `PhicommM1Server.py` | 心跳包固定为 `type:5,status:1`，未集成亮度控制 | 无法控灯 |
| 5 | `templates/index.html` | 图表数据来自前端内存（最多12条），未查询历史数据 | 无历史趋势 |
| 6 | `app.py` | 无亮度控制 API 端点 | 前端无法控灯 |
| 7 | `run.sh` | 无健康检查、日志管理、自动重启机制 | 线上不稳定 |
| 8 | 无 Dockerfile / docker-compose.yml | 部署需手动配置环境 | 部署门槛高 |

---

## 实施计划

### 阶段一：核心健壮性修复

#### 1.1 改造 `PhicommM1Server.py`
**改动要点：**
- 修复 `sqlite_conn()` 异常处理，返回 None 或抛出明确异常
- 新增数据库初始化函数（建表 + 设置数据保留策略）
- 新增历史数据清理逻辑（保留最近 N 天数据，定时执行）
- 新增亮度控制：心跳包动态拼接 `brightness` 和 `type:2`
- 新增亮度状态存储（SQLite 新表 `config` 或内存变量）

**新增表结构：**
```sql
-- 配置表，存储设备当前亮度
CREATE TABLE IF NOT EXISTS config(
    key TEXT PRIMARY KEY,
    value TEXT
);

-- 历史数据表（优化：只保留有限天数，自动清理）
-- 复用现有 m1 表，新增清理策略
```

**亮度控制协议**（参考 `src-EasyPhicommM1`）：
```
\xaaO\x01\xf2E\x119\x8f\x0b\x00\x00\x00\x00\x00\x00\x00\x00\xb0\xf8\x93\x11T/\x007\x00\x00\x02{"brightness":"<值>","type":2}\xff#END#
```
亮度取值：`0`（关）、`25`（暗）、`50`（标准）

**文件修改：** `PhicommM1Server.py`

#### 1.2 改造 `app.py`
**改动要点：**
- 修复空数据库 None 返回处理
- 新增 `/api/history` 端点（查询指定时间范围的历史数据）
- 新增 `/api/brightness` GET/POST 端点（获取/设置亮度）
- 新增 `/api/config` 端点（数据保留天数配置等）

**新增 API：**
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/history?hours=24` | GET | 获取最近N小时历史数据 |
| `/api/brightness` | GET | 获取当前亮度 |
| `/api/brightness` | POST | 设置亮度 `{"value": 50}` |
| `/api/config` | GET | 获取系统配置 |

**文件修改：** `app.py`

---

### 阶段二：前端功能增强

#### 2.1 改造 `templates/index.html`
**改动要点：**
- 图表数据源改为调用 `/api/history` 加载历史数据（支持切换时间范围：1h/6h/24h/7d）
- 新增湿度和甲醛数据的图表切换
- 新增亮度控制面板（三个按钮：关/暗/标准）
- 新增历史数据保留天数配置入口

**UI 布局规划：**
```
┌─────────────────────────────┐
│  M1空气质量监测              │
├─────────────────────────────┤
│  温度: 25.3°C  │  湿度: 60%  │
│  PM2.5: 35   │  甲醛: 0.02  │
├─────────────────────────────┤
│  亮度控制: [关] [暗] [标准]  │
├─────────────────────────────┤
│  时间范围: 1h 6h 24h 7d     │
├─────────────────────────────┤
│  [图表 - 支持多指标切换]     │
│  温度 | 湿度 | PM2.5 | 甲醛 │
└─────────────────────────────┘
```

**文件修改：** `templates/index.html`

---

### 阶段三：Docker Compose 部署

#### 3.1 创建 `Dockerfile`
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 5000 9000
CMD ["sh", "run.sh"]
```

#### 3.2 创建 `docker-compose.yml`
```yaml
services:
  m1-server:
    build: .
    container_name: phicomm-m1
    ports:
      - "5000:5000"   # Web前端
      - "9000:9000"   # M1设备TCP
    volumes:
      - ./data.db:/app/data.db   # 持久化数据库
      - ./logs:/app/logs         # 持久化日志
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:5000/"]
      interval: 30s
      timeout: 5s
      retries: 3
```

#### 3.3 创建 `requirements.txt`
```
Flask>=2.0
pytz>=2022.1
```

#### 3.4 创建 `.dockerignore`
```
__pycache__
*.pyc
.git
.gitignore
references
preview
README.md
```

**新增文件：** `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `.dockerignore`

---

### 阶段四：完善部署脚本与文档

#### 4.1 优化 `run.sh`
- 增加日志格式
- 增加进程健康检查
- 增加优雅退出信号处理

#### 4.2 更新 `README.md`
- Docker Compose 部署说明
- 亮度控制使用说明
- 数据保留配置说明

---

## 文件变更清单

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| 改 | `PhicommM1Server.py` | 健壮性+亮度控制+数据清理 |
| 改 | `app.py` | 新增API端点+空数据处理 |
| 改 | `templates/index.html` | 历史图表+亮度控制UI |
| 改 | `run.sh` | 日志+健康检查 |
| 改 | `README.md` | 更新部署说明 |
| 新 | `Dockerfile` | Docker镜像构建 |
| 新 | `docker-compose.yml` | 编排部署 |
| 新 | `requirements.txt` | Python依赖 |
| 新 | `.dockerignore` | 排除无关文件 |

---

## 风险与注意事项

1. **端口冲突**: 9000 端口需确保 M1 设备直连，不能被防火墙阻断
2. **数据迁移**: 升级时需兼容已有 `data.db`（新表用 `CREATE TABLE IF NOT EXISTS`）
3. **并发安全**: TCP 服务和 Web 服务共享 SQLite，需注意 WAL 模式或锁机制
4. **亮度值限制**: M1 仅支持 0/25/50 三档，前端需限制输入范围
5. **心跳包兼容性**: 修改心跳包结构后需在真实设备上验证
6. **数据保留默认值**: 默认保留最近 7 天数据，可通过前端配置调整

---

## 实施顺序

1. ✅ 阶段一：核心健壮性修复（PhicommM1Server.py + app.py）
2. ✅ 阶段二：前端功能增强（templates/index.html）
3. ✅ 阶段三：Docker Compose 部署（新增文件）
4. ✅ 阶段四：部署脚本与文档（run.sh + README.md）