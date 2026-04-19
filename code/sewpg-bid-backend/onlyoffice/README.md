# OnlyOffice 目录说明

这个目录现在只保留 **可并入当前 MVP 的 OnlyOffice 验证资产**，不再承载旧前端副本和历史联调环境。

## 当前保留的内容

- `onlyoffice_demo_backend.py`
  - 本地验证用 FastAPI demo
  - 能提供：
    - 文档源文件下载
    - OnlyOffice `config`
    - 文档 `meta`
    - `callback` 保存回写
    - 最终文档下载
- `docker-compose.onlyoffice.yml`
  - 只负责拉起 `onlyoffice/documentserver`
- `smoke_test.html`
  - 不依赖现有前端，直接验证 `sample.docx -> 编辑 -> 保存 -> 下载`
- `files/sample.docx`
  - 当前本地联调用 demo 文档
- `frontend_bridge_reference.md`
  - 从旧前端副本提炼出的可复用接入经验
- `requirements.txt`
  - 这个 demo 后端所需最小 Python 依赖

## 这个目录的定位

它现在的定位是：

> **OnlyOffice 独立验证与接入参考目录**

不是：

- 当前项目的正式前端目录
- 当前项目的正式后端目录
- MVP 正式接口文档目录

当前项目里真正的正式目录是：

- 前端：`/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend`
- 后端骨架：`/Users/wlb/Agent/bid-project/code/backend`
- 项目文档：`/Users/wlb/Agent/bid-project/doc`

## 哪些能直接用到当前项目

### 可以直接复用
- `onlyoffice_demo_backend.py` 里的文档会话接口设计
- `callback` 收到保存后回拉 docx 覆盖本地文件的逻辑
- `document.key` 按文件版本生成的做法
- `smoke_test.html` 作为最小本地排障页
- `docker-compose.onlyoffice.yml` 作为单独拉起 Document Server 的方式

### 只能当参考，不能原样并入
- `sample.docx` 固定 docId 模式
- 任何围绕 `sample` 的材料库编辑演示
- 旧的 mock bridge 思路

正式并入当前 MVP 时，应改成：

- FastAPI 统一承接 `/api`
- S9 走真实 OnlyOffice 文档会话
- S4/S5/S6/S8 继续由 FastAPI mock

## 哪些已经清掉了

以下内容已不再保留在本目录：

- 嵌套的 `sewpg-bid-frontend` 前端副本
- 本地 `venv`
- `main.py / main_副本.py` 双版本并存
- 旧接口草稿和长篇双入口说明

原因很简单：
- 这些内容已经和当前项目主目录重复
- 或者口径停留在旧阶段
- 留在这里会继续干扰后续接入

## 本地最短启动方式

1. 启 OnlyOffice：

```bash
docker compose -f docker-compose.onlyoffice.yml up -d
```

2. 启 demo 后端：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn onlyoffice_demo_backend:app --host 0.0.0.0 --port 8000
```

3. 打开本地 smoke 页面：

- 直接打开 `smoke_test.html`

如果页面能正常打开、编辑、保存、下载，就说明 OnlyOffice 最小闭环是通的。

## 当前建议

后续如果继续做正式接入，不要再往这个目录里塞前端副本。  
应该直接改：

- `/Users/wlb/Agent/bid-project/code/backend`
- `/Users/wlb/Agent/bid-project/code/sewpg-bid-frontend`

这个目录只保留为：

> **OnlyOffice 独立验证资产 + 接入参考**
