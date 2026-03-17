---
name: lovart-skill
description: 与 Lovart.ai 交互的技能。当需要在 Lovart.ai 上生成图片、管理 Canvas 项目时使用此技能。
---

# Lovart.ai 自动化技能

## 执行规则

**必须**通过 `run.py` 调用，禁止直接执行脚本：

```bash
python scripts/run.py <script.py> [options]
```

`run.py` 负责自动管理虚拟环境（创建 `scripts/.venv`、安装依赖、下载 Camoufox 浏览器）。

---

## 命令参考

### 认证

首次使用需登录 Lovart.ai，获取并保存 session：

```bash
python scripts/run.py patchright_auth.py
```

登录步骤：
1. 点击「开始体验」
2. 输入邮箱 + 密码
3. 输入邮件验证码
4. 跳转到 `/zh/home` 后自动保存 session（或手动输入 `ok` 确认）

Session 保存在 `scripts/data/auth/lovart.json`，有效期 30 天。

---

### Canvas 图片生成

| 命令 | 说明 | 参数 |
| ---- | ---- | ---- |
| `lovart.py --prompt` | 单张生成 | `--prompt <file>` (必填) `--output-dir` (可选) `--headless` (可选) |
| `lovart.py --batch` | 批量生成 | `--batch <dir>` (必填) `--output-dir` (可选) `--headless` (可选) |
| `lovart.py --download-all` | 补下载 | 无 |

```bash
# 单张生成（自动创建新项目）
python scripts/run.py lovart.py --prompt prompts/01.md

# 无头模式（不打开浏览器窗口）
python scripts/run.py lovart.py --prompt prompts/01.md --headless

# 批量生成（对文件夹内所有 .md 文件各创建一个项目）
python scripts/run.py lovart.py --batch prompts/

# 指定图片输出目录
python scripts/run.py lovart.py --prompt prompts/01.md --output-dir /path/to/images
python scripts/run.py lovart.py --batch prompts/ --output-dir /path/to/images --headless

# 补下载（对所有 submitted 状态的任务重新下载图片）
python scripts/run.py lovart.py --download-all
```

提示词文件为 Markdown 格式，每个文件对应一个 Lovart 项目。任务状态记录在 `scripts/data/jobs.json`，支持断点续跑。

---

### 输出说明

- 生成的图片默认保存至 `scripts/data/images/`
- 任务状态（`submitted` / 完成）记录在 `scripts/data/jobs.json`
