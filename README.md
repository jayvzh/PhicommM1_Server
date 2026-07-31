# Phicomm 悟空 M1 私有服务器

替代已停运的官方服务器，支持数据采集、历史记录、图表展示和亮度控制。

## 功能特性

- 📡 **数据采集**：TCP 服务监听 M1 设备实时数据（温度、湿度、PM2.5、甲醛）
- 💾 **历史记录**：SQLite 持久化存储，自动清理过期数据
- 📊 **图表展示**：支持温度、湿度、PM2.5、甲醛多指标切换，时间范围可选（1h/6h/24h/7d）
- 💡 **亮度控制**：支持设备屏幕亮度调节（关/暗/标准三档）
- 🐳 **Docker 部署**：一键 Docker Compose 部署

## 架构

```
M1 设备 --TCP:9000--> PhicommM1Server.py --> SQLite (data/data.db)
                                              |
Flask 前端 (端口5000) <------ app.py ----------+
```

## 快速开始

### 1. 修改路由器 Hosts

将 `aircat.phicomm.com` 指向服务器 IP：

```
<服务器IP>    aircat.phicomm.com
```

### 2. 创建 docker-compose.yml

在任意目录创建 `docker-compose.yml`：

```yaml
services:
  m1-server:
    image: jayvzh/phicomm-m1:latest
    container_name: phicomm-m1
    ports:
      - "5000:5000"   # Web前端
      - "9000:9000"   # M1设备TCP
    volumes:
      - /opt/phicomm-m1/data:/app/data       # 持久化数据库
      - /opt/phicomm-m1/logs:/app/logs       # 持久化日志
    restart: unless-stopped
    environment:
      - TZ=Asia/Shanghai
```

### 3. 启动服务

```bash
docker compose up -d
```

### 4. 访问

- 前端页面：`http://<服务器IP>:5000`
- 健康检查：`http://<服务器IP>:5000/api/health`

## 从源码构建

如需自行构建镜像：

```bash
git clone https://github.com/jayvzh/PhicommM1_Server.git
cd PhicommM1_Server
docker compose up -d --build
```

## API 接口

| 端点 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | 前端页面 |
| `/getdata` | GET | 获取最新传感器数据 |
| `/api/history?hours=N` | GET | 获取最近 N 小时的历史数据 |
| `/api/brightness` | GET | 获取当前亮度设置 |
| `/api/brightness` | POST | 设置亮度：`{"value": 0}` (0/25/50) |
| `/api/config` | GET | 获取系统配置 |
| `/api/config` | POST | 更新配置：`{"retention_days": 7}` |
| `/api/health` | GET | 健康检查 |

## 配置说明

### 数据保留

默认保留最近 7 天的历史数据，超过期限的数据会自动清理。可通过 API 修改：

```bash
curl -X POST http://localhost:5000/api/config \
  -H "Content-Type: application/json" \
  -d '{"retention_days": 30}'
```

### 亮度控制

设备支持三档亮度：`0`（关闭）、`25`（暗）、`50`（标准）。

通过前端页面按钮或 API 控制：

```bash
curl -X POST http://localhost:5000/api/brightness \
  -H "Content-Type: application/json" \
  -d '{"value": 25}'
```

## 注意事项

- 端口 9000 必须对外开放，M1 设备通过 TCP 连接此端口
- `data/` 和 `logs/` 目录需持久化挂载，避免容器重启丢失数据
- 首次使用需让 M1 设备连接 WiFi（参考 EasyLink 教程）
- 确保路由器 Hosts 正确配置，将 `aircat.phicomm.com` 指向本服务器

## License

[GPL-3.0](./LICENSE)