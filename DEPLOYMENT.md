# 云服务器部署指南

## 系统依赖（Linux）

### Ubuntu/Debian
```bash
sudo apt-get update
sudo apt-get install -y python3.10 python3-pip python3-venv
sudo apt-get install -y libasound2-dev portaudio19-dev  # edge-tts 需要
sudo apt-get install -y build-essential  # 某些 Python 包编译需要
```

### CentOS/RHEL/Amazon Linux
```bash
sudo yum install -y python3 python3-pip
sudo yum install -y alsa-lib-devel portaudio-devel  # edge-tts 需要
sudo yum groupinstall -y "Development Tools"  # 编译工具
```

## Python 环境设置

```bash
# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

## 环境变量配置

创建 `.env` 文件：
```bash
GEMINI_API_KEY=your_api_key_here
GEMINI_BASE_URL=https://api.laozhang.ai/v1
```

## 运行应用

### 开发模式
```bash
streamlit run app.py
```

### 生产模式（使用 Streamlit 内置服务器）
```bash
streamlit run app.py --server.port 8501 --server.address 0.0.0.0
```

### 使用 systemd 服务（推荐）

创建 `/etc/systemd/system/pulpit-power.service`:
```ini
[Unit]
Description=Pulpit Power AI Streamlit App
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/Theology Translation Coach
Environment="PATH=/path/to/Theology Translation Coach/venv/bin"
ExecStart=/path/to/Theology Translation Coach/venv/bin/streamlit run app.py --server.port 8501 --server.address 0.0.0.0
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable pulpit-power
sudo systemctl start pulpit-power
sudo systemctl status pulpit-power
```

## Nginx 反向代理（可选）

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
```

## 防火墙配置

```bash
# Ubuntu/Debian
sudo ufw allow 8501/tcp

# CentOS/RHEL
sudo firewall-cmd --permanent --add-port=8501/tcp
sudo firewall-cmd --reload
```

## 常见问题

### edge-tts 在服务器上无法生成音频
确保已安装系统依赖（见上方系统依赖部分），并检查临时目录权限：
```bash
chmod 777 /tmp  # 或使用自定义缓存目录
```

### 内存不足
考虑限制并发用户数或增加服务器内存。Streamlit 默认会缓存数据，可在代码中使用 `@st.cache_data(ttl=3600)` 设置缓存过期时间。

### 端口被占用
```bash
# 查找占用端口的进程
sudo lsof -i :8501
# 或使用其他端口
streamlit run app.py --server.port 8502
```


