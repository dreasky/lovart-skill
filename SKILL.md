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
| `lovart.py --prompt` | 单张生成 | `--prompt <file>` (必填) |
| `lovart.py --batch` | 批量生成 | `--batch <dir>` (必填) |
| `lovart.py --download-all` | 补下载 submitted 任务 | 无 |
| `lovart.py --retry-failed` | 重试所有失败任务 | 无 |

**可选参数**：

| 参数 | 默认值 | 说明 |
| ---- | ------ | ---- |
| `--headless` | False | 无头模式，不打开浏览器窗口 |
| `--output-dir <path>` | `scripts/data/images/` | 图片输出目录 |
| `--timeout <n>` | 300 | 最大等待时间（秒） |
| `--poll-interval <n>` | 10 | 轮询检查间隔（秒） |
| `--max-pages <n>` | 10 | 批量模式最大并发页面数 |

```bash
# 单张生成（自动创建新项目）
python scripts/run.py lovart.py --prompt prompts/01.md

# 无头模式（不打开浏览器窗口）
python scripts/run.py lovart.py --prompt prompts/01.md --headless

# 批量生成（保留页面等待，最多 10 个并发页面）
python scripts/run.py lovart.py --batch prompts/

# 指定图片输出目录
python scripts/run.py lovart.py --prompt prompts/01.md --output-dir /path/to/images

# 自定义等待参数：超时 5 分钟，每 30 秒检查一次
python scripts/run.py lovart.py --batch prompts/ --timeout 300 --poll-interval 30

# 自定义并发页面数：最多同时打开 5 个页面
python scripts/run.py lovart.py --batch prompts/ --max-pages 5

# 补下载（对所有 submitted 状态的任务下载图片）
python scripts/run.py lovart.py --download-all

# 重试所有失败的任务
python scripts/run.py lovart.py --retry-failed
```

提示词文件为 Markdown 格式，每个文件对应一个 Lovart 项目。任务状态记录在 `scripts/data/jobs.json`，支持断点续跑。

**执行流程**：
1. 发送 prompt 后等待 `IMAGE_GENERATING` 元素出现（最多 30 秒）
2. 若超时未出现，标记失败并记录错误原因
3. 提交成功后**保留页面**，轮询检查图片状态
4. 批量模式使用信号量控制并发页面数（默认最多 10 个）
5. 检测到图片 ready 则下载，generating 则等待完成
6. 超时或出错则标记失败，记录错误原因
7. 使用 `--retry-failed` 重试所有失败任务

---

### 输出说明

- 生成的图片默认保存至 `scripts/data/images/`
- 任务状态记录在 `scripts/data/jobs.json`
- 失败任务包含 `error` 字段说明失败原因

**Job 状态**：
- `pending` - 待处理
- `submitted` - 已提交，等待图片
- `done` - 完成
- `failed` - 失败（查看 `error` 字段了解原因）