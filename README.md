# Worklog

把 Codex 和 Claude 的聊天记录整理成工作日志与周报。Worklog 在本机读取对话、识别工作事件并生成报告，适合想保留工作记录、又不想每天从头写日志的人。

- **代码模式**：通过规则和固定模板生成日报、周报，不调用外部模型，不消耗模型 token。
- **AI 模式（实验性）**：主动调用 OpenAI、Anthropic 或兼容接口，对工作内容进行精炼。
- **本地工作台**：React 界面与 FastAPI 服务均运行在本机，SQLite 保存对话与报告。
- **Excel 输出**：生成包含「报告」「工作事件」「对话证据」的 `.xlsx` 文件。

当前版本为 **0.1.0 MVP**。它可以用示例数据完成「导入 → 时间线 → 生成日报 / 周报 → 导出」流程；完整产品计划中的部分交互仍在开发中。

## 功能状态

| 功能 | 当前支持情况 |
| --- | --- |
| 导入 | Codex / Claude 的部分 JSON、JSONL、NDJSON 及简单 Markdown 导出格式，见[格式说明](docs/format-adapters.md) |
| 重复检测 | 同一来源文件内容未变时跳过；内容变化后更新该会话的消息 |
| 本地分析 | 根据关键词识别完成、进行中、阻塞、决策和下一步，保留证据消息编号 |
| 日报 / 周报 | CLI 和 Web 均可生成，默认中文 |
| Markdown / HTML / Excel | 后端自动生成文件；CLI 可指定格式导出；API 可下载 |
| Web 编辑 | 可以修改草稿并复制 Markdown；编辑内容暂不回写数据库或已导出文件 |
| 模型接口 | OpenAI、Anthropic，以及手动配置的 CCSwitch / 兼容中转接口 |
| PPT | 已有渲染器原型；自动报告导出尚未接入 CLI、API 与 Web |

## 本地运行

建议使用 **Python 3.12** 和 **Node.js 22.12+**。Python 包声明支持 3.9+；当前前端依赖要求 Node.js 20.19+ 或 22.12+。以下命令在 macOS / Linux 的项目根目录执行。

先下载或克隆本仓库，进入包含 `pyproject.toml` 的目录，然后安装后端：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

启动后端，保持这个终端运行：

```bash
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

另开一个终端，进入项目根目录，安装并启动前端：

```bash
cd apps/web
npm ci
npm run dev -- --host 127.0.0.1 --port 5173
```

打开 [http://127.0.0.1:5173/](http://127.0.0.1:5173/)。请使用此地址访问；直接双击 `apps/web/index.html` 无法运行应用。API 文档位于 [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)。

如果页面提示连接失败，确认两个终端都在运行，且端口未被其他程序占用。在 Windows 上，虚拟环境激活命令为 `.venv\Scripts\Activate.ps1`。

默认仅绑定本机地址。当前 API 没有登录鉴权，并且能读取指定的本地目录；请保持本机使用，不要直接开放到公网或局域网。

## 先用示例体验

在项目根目录、已激活虚拟环境的终端中执行：

```bash
worklog scan tests/fixtures
worklog import tests/fixtures
worklog daily --date 2026-10-10
worklog weekly --week 2026-W41
```

也可以在 Web 的「导入」页填写 `tests/fixtures`，然后到「日报」页选择 `2026-10-10`，点击「代码模式」。相对路径以启动后端时所在的目录为基准。

示例文件是脱敏的测试对话。导入自己的记录时，填写聊天导出文件或目录的绝对路径；格式不兼容时，请参考[适配器说明](docs/format-adapters.md)，不要把真实聊天记录直接提交到 Issue。

规则模式只是草稿整理工具。它根据消息文本判断工作状态，不验证实际代码、测试或交付物；例如一句同时含有「修复」和「问题」的话可能被归入阻塞，提交工作报告前需要人工检查。

## 导出 Markdown、HTML 和 Excel

日报、周报生成时会同时写入三种文件，默认目录为 `.worklog/exports/`。

```bash
worklog export --format markdown --date 2026-10-10
worklog export --format html --date 2026-10-10
worklog export --format excel --date 2026-10-10
worklog export --format excel --week 2026-W41
```

例如，Excel 周报输出到 `.worklog/exports/weekly-2026-W41.xlsx`。CLI 的 `--db` 指定数据库，`--output` 指定导出目录：

```bash
worklog export --format excel --week 2026-W41 \
  --db .worklog/worklog.db --output .worklog/exports
```

Web 目前提供「复制 Markdown」。Excel、HTML 文件可在本地导出目录获取，也可访问 API，例如：

```text
http://127.0.0.1:8000/api/reports/daily/download?date_value=2026-10-10&format=xlsx
http://127.0.0.1:8000/api/reports/weekly/download?week=2026-W41&format=html
```

下载接口会重新生成代码模式报告，不会导出浏览器里尚未保存的修改或此前的 AI 草稿。相同日期 / 周次的生成操作会覆盖对应导出文件，需要保留旧版本时请先复制文件或指定新的输出目录。

## CCSwitch 与外接模型

聊天记录来自 Claude 还是 Codex，与用于精炼报告的模型接口是两个独立选择。使用兼容中转的用户可以在「AI 设置」页手动填写已在自己环境中可用的接口。

1. 「服务商」选择 `CCSwitch 中转`。
2. 「兼容协议」选择中转支持的 `OpenAI Compatible` 或 `Anthropic Compatible`。
3. 「Base URL」填写实际服务地址。示例 `http://127.0.0.1:8317/v1` 只是格式演示，不代表 CCSwitch 的固定地址或端口。
4. 「模型名」填写中转端实际支持的模型标识；有鉴权要求时填写 API Key。
5. 点击「保存接口配置」，再到日报 / 周报页主动使用「AI 模式」。

Worklog 不会安装或启动 CCSwitch，也不会自动读取它的配置。CCSwitch 中的配置必须对应一个实际可访问、兼容所选协议的 API 服务。**中转模式请明确填写 Base URL**，留空时当前实现会使用所选协议的官方服务地址。

OpenAI 兼容协议使用 Chat Completions；Anthropic 兼容协议使用 Messages。填写以 `/v1` 结尾的地址时会补全相应请求路径，也可以填写完整的 `/v1/chat/completions` 或 `/v1/messages` 地址。模型需支持返回结构化 JSON；部分兼容服务不支持 OpenAI 的 `response_format` 参数，调用失败时应检查中转能力。

AI 模式默认会发送报告期间的工作摘要以及关联消息的前 1,200 个字符，这些摘要和片段也可能含有敏感信息。当前 Web 尚未接入发送预览、逐条选取片段和脱敏设置；若需要这些控制，请先使用代码模式。完整说明见[隐私与数据说明](docs/privacy.md)。

## 数据与密钥

默认在启动命令的当前目录下创建：

```text
.worklog/
├── worklog.db               # 原始消息、来源路径、工作事件和报告
├── provider-settings.json  # 服务商、协议、Base URL 和模型名
└── exports/                # Markdown、HTML 和 Excel 导出
```

API 可通过 `WORKLOG_DB` 环境变量指定数据库。前端可通过 `VITE_WORKLOG_API` 指定 API 地址；若修改前端访问来源，还需相应配置后端 CORS。默认开发来源为 `localhost:5173` 和 `127.0.0.1:5173`。

API Key 优先读取 `WORKLOG_OPENAI_API_KEY`、`WORKLOG_ANTHROPIC_API_KEY` 或 `WORKLOG_CCSWITCH_API_KEY` 环境变量，也可在设置页保存。保存时尝试写入系统密钥链；密钥链不可用时只在进程内存中保留，服务重启后需重新输入。密钥不会作为配置项写入 SQLite、导出文件或 `provider-settings.json`。

仓库忽略本地数据目录、数据库、环境变量文件、虚拟环境和前端依赖。导出的报告可能包含原始对话证据，请按原始聊天记录的敏感级别处理。

## 开发与贡献

```bash
python -m unittest discover -s tests -v
```

在 `apps/web` 目录构建前端：

```bash
npm run build
```

项目结构：

```text
worklog/core/          # 适配器、导入、规则分析、模型接口、渲染和存储
worklog/cli.py         # 命令行入口
apps/api/             # FastAPI 服务
apps/web/             # React + TypeScript + Vite 工作台
tests/fixtures/       # 脱敏测试数据
docs/                 # 格式与隐私说明
```

欢迎提交 Issue 和 Pull Request。报告解析问题时请提供最小、脱敏的样例，说明来源工具版本和预期结果。

后续重点：完整的发送预览与脱敏流程、Web 保存与多格式下载、PPTX 报告导出、来源证据面板、项目与事件编辑、更多真实格式适配。桌面包装、云同步、团队协作和后台监听不在当前版本范围内。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。
