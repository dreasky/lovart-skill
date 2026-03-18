# lovart-skill

Lovart.ai 浏览器自动化工具，基于 [Camoufox](https://github.com/daijro/camoufox)（Firefox 反检测浏览器），可绕过 Cloudflare Turnstile 验证。

## 项目结构

```
lovart-skill/
├── requirements.txt
├── README.md
└── scripts/
    ├── run.py              # 统一入口，管理环境与依赖
    ├── patchright_auth.py  # 认证模块
    ├── session.py          # 会话客户端
    ├── lovart.py           # Canvas 自动化主脚本
    └── example.py          # 使用示例
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

**批量生成**（串行提交所有提示词，再并行等待生图完成）：

```bash
python scripts/run.py lovart.py --batch prompts/
```

批量模式流程：
1. 串行依次为每个 `.md` 文件创建项目并发送提示词
2. 全部提交后，轮询所有项目页面，图片就绪即下载
3. 已完成（`done`）的任务自动跳过；失败任务重入时先检测是否已有图片，有则直接下载

**指定图片输出目录**（默认 `scripts/data/images/`）：

```bash
python scripts/run.py lovart.py --prompt prompts/01.md --output-dir D:\MyImages
python scripts/run.py lovart.py --batch prompts/ --output-dir D:\MyImages --headless
```

**补下载**（对所有 `submitted` 状态的任务重新下载图片）：

```bash
python scripts/run.py lovart.py --download-all
```

每个提示词文件对应一个 Lovart 项目，任务状态记录在 `scripts/data/jobs.json`，支持断点续跑。

## 编写自动化脚本

使用 `LovartSession` 上下文管理器：

```python
from session import LovartSession

with LovartSession(headless=False) as session:
    if not session.is_logged_in():
        print("Session expired.")
        exit(1)

    page = session.page
    # 在此编写自动化逻辑
    page.goto("https://www.lovart.ai/zh/home")
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
