# 水质三维荧光光谱指纹平台 - Web 版

前后端分离架构，后端基于 **FastAPI**（Python），前端为单页应用（HTML + Plotly.js）。
未选择 Node.js 是因为：核心算法（SG 滤波、Delaunay 插值、FRI 积分、SQLite 库）已在 Python 中实现，
重写 JS 版意义不大；FastAPI 性能与开发体验都优秀，且能与桌面端共用同一份算法。

## 安装

```bash
pip install -r requirements.txt
```

## 启动

Windows：
```cmd
start_server.bat
```

Linux/macOS：
```bash
chmod +x start_server.sh && ./start_server.sh
```

直接运行：
```bash
python server.py
```

启动后浏览器访问：
- 前端界面：http://localhost:8000/
- 自动生成的 API 文档：http://localhost:8000/docs

## 配置

通过环境变量：

| 变量 | 默认 | 说明 |
|------|------|------|
| `EEM_HOST` | `0.0.0.0` | 监听地址 |
| `EEM_PORT` | `8000` | 监听端口 |
| `EEM_LIB`  | `eem_library.sqlite` | 指纹库文件路径 |

## 文件结构

```
D:\spectrum_NEW\
├── server.py                  # FastAPI 后端服务
├── eem_fingerprint.py         # 核心算法（共用）
├── fingerprint_db.py          # SQLite 指纹库（共用）
├── eem_visualizer.py          # 桌面端可视化（GUI 用）
├── eem_gui.py                 # 桌面 PyQt5 入口（可选）
├── static/
│   ├── index.html             # 前端入口
│   ├── style.css              # 科技风样式
│   └── app.js                 # 前端逻辑
├── start_server.bat / .sh     # 启动脚本
├── requirements.txt
├── blank.csv                  # 示例：空白
└── industrial.csv             # 示例：工业废水
```

## REST API

| 方法 | 路径 | 用途 |
|------|------|------|
| GET  | `/` | 前端 SPA 入口 |
| GET  | `/api/health` | 服务健康检查 |
| POST | `/api/process` | 上传 blank+sample 进行预处理与特征提取（multipart/form-data） |
| GET  | `/api/library/list` | 列出库内全部指纹摘要 |
| GET  | `/api/library/{id}` | 获取指定指纹的完整数据（含 EEM 矩阵） |
| POST | `/api/library/add` | 把会话中的指纹写入库（需 `session_id`） |
| DELETE | `/api/library/{id}` | 删除指纹 |
| POST | `/api/library/search` | 余弦+欧式综合检索 |
| POST | `/api/compare` | 两个会话指纹的成对比对 |

API 详细字段、字段类型、示例请求都可在 `/docs` 自动文档中查看。

## 前端架构

- 纯静态文件，无需打包工具
- Plotly.js 通过 CDN 加载（`https://cdn.plot.ly/plotly-2.32.0.min.js`）
- 全局状态在 `STATE` 对象中维护，会话 ID（`session_id`）由后端返回，
  保证后续 `add` / `search` / `compare` 操作能复用上一次的预处理结果

## 设计风格

| 元素 | 说明 |
|------|------|
| 主色 | 霓虹青 `#4ce8ff`，副色 霓虹品红 `#ff5cf7` |
| 背景 | 深蓝黑 `#060B18` + 网格图案 + 弥散光晕 |
| 字体 | 标题/数据：等宽 (JetBrains Mono / Consolas)；正文：思源黑体 / Microsoft YaHei |
| 动效 | Loading 扫描线、按钮 hover 发光、面板顶部细长指示线 |
| 上传 | 支持点击或拖拽 CSV 文件 |

## 与桌面 GUI 的关系

桌面端（`eem_gui.py`）和 Web 端（`server.py`）共用同一份算法模块，
任何修改 `eem_fingerprint.py` 或 `fingerprint_db.py` 都会同时生效。
两端可以共用同一个 SQLite 指纹库（默认 `eem_library.sqlite`）。
