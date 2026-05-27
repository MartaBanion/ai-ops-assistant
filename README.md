# AI Ops Assistant · 智能运维故障助手

一个基于 FastAPI + DeepSeek AI 的智能运维故障分析工具。粘贴 Linux / Docker / Nginx / Kubernetes 等报错日志，AI 自动分析故障原因并给出排查命令和解决方案。

---

## 功能特性

- **🔍 智能故障分析** — 支持 Linux 系统、Docker、Nginx、Kubernetes 等常见运维场景
- **⚡ 本地知识库优先** — 内置常见故障（端口冲突、磁盘满、权限不足等）知识库，命中后秒级响应，不消耗 API
- **🤖 DeepSeek AI 驱动** — 本地知识库未命中时，调用 DeepSeek API 进行深度分析
- **📋 可执行排查命令** — 每条故障分析附带具体排查命令，一键复制使用
- **📚 历史记录** — 所有分析记录持久化存储，支持分页查询
- **🎨 现代 Web 界面** — 深色主题、响应式布局，适合运维场景使用

## 快速开始

### 前置要求

- Python 3.6+
- pip

### 1. 克隆仓库

```bash
git clone https://github.com/MartaBanion/ai-ops-assistant.git
cd ai-ops-assistant
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置 API Key

在项目根目录创建 `.env` 文件：

```
DEEPSEEK_API_KEY=你的DeepSeek_API_Key
```

> **注意：** 不配置 API Key 也可以使用，本地知识库的故障匹配功能不受影响。只有本地知识库未命中时，才会需要调用 DeepSeek API。

### 4. 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5. 访问页面

浏览器打开 [http://localhost:8000](http://localhost:8000)

## 使用方式

### Web 界面

1. 在输入框中粘贴报错日志（Linux 系统日志、Docker 报错、Nginx 错误等）
2. 点击 **分析** 按钮
3. AI 自动返回：
   - **故障类型** — 问题归类
   - **原因分析** — 通俗易懂的原因说明
   - **排查命令** — 可直接执行的 Linux 命令
   - **解决方案** — 分步骤的解决建议
   - **风险等级** — safe / info / warning / danger

### API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/analyze` | 分析报错日志 |
| `GET` | `/api/history` | 获取历史记录（支持分页） |
| `GET` | `/api/history/{id}` | 获取单条记录详情 |
| `GET` | `/api/health` | 健康检查 |

## 本地知识库

项目内置了以下常见故障的本地知识库，匹配关键词即可秒级响应：

| 故障类型 | 风险等级 |
|----------|----------|
| 服务未启动 / 端口未监听 | ⚠️ warning |
| 磁盘空间已满 | 🔴 danger |
| 权限不足 | ⚠️ warning |
| Docker 未安装 | ℹ️ info |
| Docker 容器异常退出 | ⚠️ warning |
| Nginx 网关错误 (502/504) | 🔴 danger |
| 资源不存在或路径错误 | ℹ️ info |
| 内存不足 (OOM) | 🔴 danger |
| 端口冲突 | ℹ️ info |
| Kubernetes Pod 反复重启 | ⚠️ warning |
| Kubernetes 镜像拉取失败 | ⚠️ warning |

## 技术栈

- **后端框架** — FastAPI
- **AI 模型** — DeepSeek Chat API
- **数据库** — SQLite
- **前端** — Tailwind CSS + Font Awesome
- **运行时** — Uvicorn + Python 3

## 项目结构

```
ai-ops-assistant/
├── main.py              # FastAPI 应用入口
├── ai_service.py        # AI 分析服务 + 本地知识库
├── database.py          # SQLite 数据库操作
├── models.py            # Pydantic 数据模型
├── static/
│   └── index.html       # 前端页面
├── requirements.txt     # Python 依赖
└── .env                 # 环境变量配置
```

## License

MIT
