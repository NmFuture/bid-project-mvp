# OpenCode FastAPI Word Skill Demo

一个最小可跑的 FastAPI demo，用来把后端请求转成：

- `opencode run`
- 可选 `--dangerously-skip-permissions`
- 显式要求使用某个 OpenCode skill
- 输入一个 `.docx`
- 产出一个新的 `.docx`

这个 demo 适合你们先把链路打通，再决定后面要不要接队列、对象存储、数据库。

## 目录

```text
/Users/sean/Documents/opencode-fastapi-word-skill-demo
├── app/
│   └── main.py
├── data/
│   └── jobs/
├── README.md
└── requirements.txt
```

## 适用场景

- FastAPI 接一个“处理 Word”请求
- 把任务交给 OpenCode
- 让 OpenCode 用已安装的 skill 处理文档
- 最终下载生成的 `.docx`

## 重要限制

- 这版 demo 只支持 `.docx`
- 任务状态持久化在本地 JSON 文件里，不是数据库
- 任务执行器是应用内 `asyncio.create_task`，适合 demo，不适合高可靠生产
- 最终产物通过文件下载接口返回，不会把 400MB 的 Word 塞进 JSON
- 是否能成功调用某个 skill，取决于这台机器上的 OpenCode 当前是否安装了那个 skill

## 为什么适合大文件

- 如果你已经有本地文件路径，优先走 `/jobs/from-path`
- 这条路不会复制 400MB 文件内容，只会在 job 目录里建立一个符号链接
- 生成结果落盘后通过下载接口流式返回

## 安装

```bash
cd /Users/sean/Documents/opencode-fastapi-word-skill-demo
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 启动

```bash
cd /Users/sean/Documents/opencode-fastapi-word-skill-demo
source .venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

打开健康检查：

```bash
curl http://127.0.0.1:8000/health
```

## API

### 1. 用本地路径创建任务

更适合大文件。

```bash
curl -X POST http://127.0.0.1:8000/jobs/from-path \
  -H 'Content-Type: application/json' \
  -d '{
    "input_path": "/absolute/path/to/input.docx",
    "task": "Use the officecli skill to update the cover page and regenerate a client-ready report.",
    "skill_name": "officecli",
    "yolo": true,
    "output_filename": "final-report.docx"
  }'
```

### 2. 上传文件创建任务

适合小一些的 Word；400MB 更建议走本地路径模式。

```bash
curl -X POST http://127.0.0.1:8000/jobs/upload \
  -F 'file=@/absolute/path/to/input.docx' \
  -F 'task=Use the officecli skill to clean formatting and produce a final client-ready document.' \
  -F 'skill_name=officecli' \
  -F 'yolo=true' \
  -F 'output_filename=final-output.docx'
```

### 3. 查询任务

```bash
curl http://127.0.0.1:8000/jobs
curl http://127.0.0.1:8000/jobs/<job_id>
```

### 4. 查看日志

```bash
curl http://127.0.0.1:8000/jobs/<job_id>/logs
```

### 5. 下载产物

```bash
curl -L http://127.0.0.1:8000/jobs/<job_id>/artifact -o result.docx
```

## OpenCode 提示

这版会向 OpenCode 发送类似这样的 prompt：

```text
Use the officecli skill.
The source Word file is at "/path/to/input.docx".
The output Word file must be written to "/path/to/output.docx".
You must produce a valid .docx file at the output path.
Task:
<your task>
```

如果 `yolo=true`，命令会变成：

```bash
opencode run --format json --dir <job_dir> --dangerously-skip-permissions "<prompt>"
```

## 可配环境变量

- `OPENCODE_BIN`: 自定义 `opencode` 可执行文件路径
- `OPENCODE_DEFAULT_SKILL`: 默认 skill 名称，默认是 `officecli`

示例：

```bash
export OPENCODE_BIN=/Users/sean/.opencode/bin/opencode
export OPENCODE_DEFAULT_SKILL=officecli
```

## 后续如果要上生产

建议下一步补这些：

- 用 Celery / RQ / Dramatiq / Arq 跑后台任务
- 用 PostgreSQL 或 Redis 记录 job 状态
- 用对象存储存放输入输出大文件
- 增加回调、重试、超时和并发限制
- 对可访问目录做白名单，别把整个磁盘暴露给 OpenCode
