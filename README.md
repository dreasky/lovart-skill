# lovart-skill

Lovart.ai 浏览器自动化工具，基于 [Camoufox](https://github.com/daijro/camoufox)（Firefox 反检测浏览器），可绕过 Cloudflare Turnstile 验证。

## 项目结构

```txt
lovart-skill/
├── requirements.txt
├── README.md
└── scripts/
    ├── run.py                  # 统一入口，管理环境与依赖
    ├── patchright_auth.py      # 认证入口脚本
    ├── lovart.py               # Canvas 自动化入口脚本
    ├── example.py              # 使用示例
    └── lovart/                 # 核心包
        ├── __init__.py         # 包入口，导出公共 API
        ├── config.py           # 全局配置常量
        ├── auth/               # 认证模块
        │   ├── __init__.py
        │   ├── models.py       # AuthState, StorageOrigin 数据类
        │   ├── store.py        # AuthStore 持久化仓库
        │   └── authenticator.py # Authenticator 认证编排器
        ├── models/             # 任务模型
        │   ├── __init__.py
        │   └── job.py          # Job, JobStatus 数据类
        └── services/           # 服务层
            ├── __init__.py
            ├── job_store.py    # Job 仓库
            ├── canvas.py       # Canvas 页面操作服务
            └── session.py      # LovartSession 会话管理
```

## 架构设计

### 设计模式

| 模式 | 位置 | 说明 |
|------|------|------|
| **数据类** | `models/job.py`, `auth/models.py` | 使用 `@dataclass` 定义数据结构，包含序列化方法 |
| **枚举** | `JobStatus` | 类型安全的状态值，替代字符串常量 |
| **仓库模式** | `JobStore`, `AuthStore` | 封装数据持久化，提供 CRUD 接口 |
| **服务层** | `CanvasService` | 封装页面操作，单一职责 |
| **工厂方法** | `Job.create()`, `AuthState.from_dict()` | 对象创建逻辑封装 |
| **策略模式** | `ImageWaiter` | 封装等待和重试策略 |

### 模块职责

```txt
┌─────────────────────────────────────────────────────────────┐
│                     入口脚本 (Entry Points)                   │
│  lovart.py │ patchright_auth.py                             │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                      runners (执行编排)                       │
│  JobRunner - 任务提交、图片下载、批量处理                       │
│  ImageWaiter - 等待、重试、状态检测                            │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                     services (服务层)                         │
│  CanvasService - 页面导航、对话框、输入、图片下载               │
│  LovartSession - 会话管理、浏览器上下文                        │
│  JobStore / AuthStore - 数据持久化                           │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                      models (数据模型)                        │
│  Job, JobStatus - 任务状态                                   │
│  AuthState, StorageOrigin - 认证状态                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                       config (配置)                           │
│  URLs, 路径, 选择器, 超时常量                                  │
└─────────────────────────────────────────────────────────────┘
```

### 公共 API

```python
from lovart import (
    # 配置
    Config,
    # 数据模型
    Job, JobStatus,
    # 服务
    JobStore, CanvasService, LovartSession,
    # 执行器
    JobRunner, ImageWaiter,
    # 认证
    AuthState, AuthStore, Authenticator,
)
```

## 快速开始

### skill安装

```bash
npx skills add https://github.com/dreasky/lovart-skill --skill lovart-skill
```

### 1. 认证

首次使用需要登录 Lovart.ai，获取并保存 session：

```bash
python scripts/run.py patchright_auth.py
```

脚本会自动：

- 创建虚拟环境并安装依赖
- 下载 Camoufox Firefox 浏览器
- 打开浏览器，等待手动完成登录

登录步骤：

1. 点击「开始体验」
2. 输入邮箱 + 密码
3. 输入邮件验证码
4. 跳转到 `/zh/home` 后自动保存 session（或手动输入 `ok` 确认）

Session 保存在 `scripts/data/auth/lovart.json`，有效期 30 天。

### 2. 运行 Canvas 自动化

准备提示词文件（Markdown 格式）：

```markdown
# prompt.md 内容示例
a futuristic city at night, neon lights, cinematic
```

**单张生成**（自动创建新项目，记录 projectId 到 `jobs.json`）：

```bash
python scripts/run.py lovart.py --prompt prompts/01.md
```

**无头模式**（不打开浏览器窗口）：

```bash
python scripts/run.py lovart.py --prompt prompts/01.md --headless
```

**批量生成**：

```bash
python scripts/run.py lovart.py --batch prompts/
```

批量模式流程（稳定性优先）：

1. 串行提交：依次为每个 `.md` 文件创建项目、发送提示词、关闭页面
2. 独立等待：每个任务独立计时，等待指定时间后重新打开页面检查
3. 智能检测：检测图片状态（已就绪/生成中/无），生成中则等待完成
4. 自动重试：无图片时重新提交 prompt，最多重试 3 次
5. 状态保持：重试耗尽后保留 `SUBMITTED` 状态，便于后续手动处理

**指定图片输出目录**（默认 `scripts/data/images/`）：

```bash
python scripts/run.py lovart.py --prompt prompts/01.md --output-dir D:\MyImages
python scripts/run.py lovart.py --batch prompts/ --output-dir D:\MyImages --headless
```

**自定义等待参数**：

```bash
# 等待 5 分钟，最多重试 5 次
python scripts/run.py lovart.py --batch prompts/ --wait-seconds 300 --max-retries 5
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--wait-seconds` | 180 | 每次检查的等待时间（秒） |
| `--max-retries` | 3 | 最大重试次数 |

**补下载**（对所有 `submitted` 状态的任务重新下载图片）：

```bash
python scripts/run.py lovart.py --download-all
```

每个提示词文件对应一个 Lovart 项目，任务状态记录在 `scripts/data/jobs.json`，支持断点续跑。

## 编写自动化脚本

### 基础用法

使用 `LovartSession` 上下文管理器：

```python
from lovart import LovartSession

with LovartSession(headless=False) as session:
    if not session.is_logged_in():
        print("Session expired.")
        exit(1)

    page = session.page
    # 在此编写自动化逻辑
    page.goto("https://www.lovart.ai/zh/home")
```

### 使用核心包

```python
from pathlib import Path
from lovart import Job, JobStatus, JobStore, JobRunner, CanvasService, LovartSession

# 初始化（可自定义等待参数）
store = JobStore()
runner = JobRunner(store, wait_seconds=180, max_retries=3)

with LovartSession(headless=True) as session:
    if not session.is_logged_in():
        exit(1)

    # 运行单个任务（自动处理等待和重试）
    runner.run_single(session.page, Path("prompts/01.md"), session)

    # 批量运行
    prompts = sorted(Path("prompts").glob("*.md"))
    runner.run_batch(prompts, session)
```

`LovartSession` 参数：

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `headless` | bool | `False` | 是否无头模式运行浏览器 |
| `reauth_if_needed` | bool | `True` | 无 session 时是否自动触发认证 |

## 依赖

- Python 3.10+
- [camoufox](https://github.com/daijro/camoufox) — Firefox 反检测浏览器，用于通过 Cloudflare Turnstile
- python-dotenv

依赖由 `run.py` 自动管理，无需手动安装。首次运行任意命令时会自动完成：

1. 创建 `scripts/.venv` 虚拟环境
2. 安装 `requirements.txt` 中的依赖
3. 下载 Camoufox Firefox 浏览器二进制

后续运行会检测 `requirements.txt` 是否变化，仅在变化时重新安装。

## 更新日志

### v2.1.0 - 稳定性优化

- **关闭页面等待**：提交后关闭页面，减少资源占用，提升稳定性
- **智能状态检测**：检测图片状态（就绪/生成中/无），生成中则等待完成
- **自动重试机制**：无图片时重新提交 prompt，可配置等待时间和重试次数
- **独立计时**：批量模式下各任务独立计时，互不干扰
- **状态保持**：重试耗尽后保留 `SUBMITTED` 状态
- **新增参数**：`--wait-seconds`, `--max-retries`
- **模块整合**：`LovartSession` 移入 `lovart/services/`，删除 `session.py`

### v2.0.0 - 面向对象重构

- **模块化拆分**：将单文件脚本拆分为 `lovart` 核心包
- **数据模型**：引入 `Job`, `JobStatus`, `AuthState` 数据类
- **仓库模式**：`JobStore`, `AuthStore` 封装持久化逻辑
- **服务层**：`CanvasService` 封装所有页面操作
- **类型安全**：使用枚举替代字符串常量
