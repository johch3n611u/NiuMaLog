# Worklog

把 Codex / Claude 的聊天記錄整理成工作日志與週報的 local-first 個人工具。目前唯一的實作在 [`PythonVersion/`](PythonVersion/)。

本文件回答一個假設性問題：**如果要優化，佈署要選最簡單、能同時容納 Linux / macOS / Windows 的方案，同時兼顧效能與未來開發需求 —— 哪種架構與語言的組合是最優解？**

---

## 一、現況盤點

以下都是實際讀代碼量到的事實，不是從 README 轉述。

### 規模

| 部分 | 行數 |
| --- | --- |
| Python（core + cli + api） | 約 1,400 |
| React + TypeScript 前端 | 約 170 |
| 測試 | 111 行 / 7 個 test |

### 依賴實況（與 `pyproject.toml` 的宣告不符）

| 套件 | 宣告 | 實際 |
| --- | --- | --- |
| `fastapi` / `uvicorn` | 必要 | 僅 `apps/api` 使用，且被 `try: ... except ImportError: app = None` 保護 |
| `pydantic` | 必要 | **程式碼零引用**（domain 用 dataclass） |
| `typer` | 必要 | **程式碼零引用**（cli 用 `argparse`） |
| `keyring` | 必要 | 選用，`import` 失敗時靜默降級 |
| `pytest` / `httpx` | dev | **零引用**（測試是 `unittest`） |

真正值得注意的是：`worklog/core/` **完全只用標準庫**。xlsx 與 pptx 不是靠 `openpyxl` / `python-pptx`，而是用 `zipfile` + `xml.etree` 手搓 OOXML。這是一個既有的、可以刻意維持的資產。

### 佈署資產：零

沒有 Dockerfile、沒有 CI、沒有打包腳本、沒有發行流程、沒有資料庫 migration 機制。README 只給 macOS / Linux 指令，Windows 僅有一行 venv 啟用提示。

---

## 二、效能：先量到的是結構問題，不是語言問題

這一節的結論來自讀代碼，不需要跑 profile 就能確認。

`WorklogService.build_document()` 是所有報告生成的必經之路，它做的事：

1. 呼叫 `refresh_events()` —— 從 SQLite **全量**取回所有訊息，重跑一次關鍵詞分析器，**全量**重寫 `work_events` 表
2. 再呼叫一次 `storage.list_all_messages()` —— 把**同一份**訊息再次全量物化成 Python 物件，用來查證據

也就是說：**每生成一份日報/週報，全部訊息被載入成 Python 物件兩次，並且全量重跑一次分析器。**

這是 O(n) 的全量重算。換成 Go 或 Rust，仍然是 O(n) 的全量重算，只是常數變小。

因此效能優化的正確順序是：

1. **持久化分析結果**，只對新增/變更的對話做增量分析（`conversations.source_hash` 已經存在，可作為變更偵測的鍵）
2. **合併兩次全量載入**，證據查詢改用 `WHERE id IN (...)` 的 SQL，不要把整張表物化
3. `generate()` 目前呼叫兩次 `storage.save_report()`，屬冗餘寫入

做完以上再量測。**在沒有 profile 的情況下斷言「語言不是瓶頸」，是不成立的**——常數差異會把可接受規模往後推。準確的說法是：瓶頸優先在資料流與演算法，語言是**尚未量測**的次要因子。

---

## 三、佈署選項評估

評估標準：使用者在 Linux / macOS / Windows 三平台上「拿到就能跑」的摩擦有多低。

| 方案 | 三平台摩擦 | 實際代價 | 判定 |
| --- | --- | --- | --- |
| **`uv tool install worklog`** | 極低（一行指令） | 需先有 Python / uv | **工程師自用的首選** |
| **PyInstaller `one-dir`** | 低（解壓即用目錄） | 需三平台各建一次 + 簽章 | **要發給非工程師時的首選** |
| PyInstaller `onefile` | 最低（單一檔案） | 每次啟動解壓暫存、冷啟動慢、易被防毒誤報、難除錯 | 量到冷啟動可接受前，不要選 |
| Docker | **不適用** | 只解 Linux 伺服器，local-first 個人工具用不上 | 排除 |
| Tauri 2 + Python sidecar | 高 | 引入 Rust + Node + Python 三套工具鏈；Linux 端 webkit2gtk 版本分裂 | 現在不做 |
| Go / Rust 重寫 | 最低（真正單檔、可交叉編譯） | 放棄 1,400 行已驗證邏輯與格式适配器知識 | **現在不做** |
| Nuitka | 同 PyInstaller | 仍要處理三平台 runtime 與簽章，只可能讓執行期快一點 | 無明顯優勢 |

### 幾個容易被低估的坑

- **PyInstaller 不能交叉編譯。** Windows / macOS / Linux 必須各建一次。但要注意：換成 Go 也**省不掉**「三平台各驗證一次 + 簽章 + 公證」，只省掉「三平台各建置一次」。
- **完整包不是純標準庫。** `fastapi` 依賴 `pydantic`，而 pydantic v2 的核心 `pydantic-core` 是 Rust 寫的、**平台專屬的編譯 wheel**。「core 純 stdlib」這個資產只對**純 CLI build** 成立，含 UI 的完整包沒有這個保證。另外 `keyring` 在凍結環境下的後端發現（Windows Credential Manager / macOS Keychain / Linux Secret Service）常需額外 hook。
- **Linux 產物受 glibc 版本綁定。** 在新 glibc 上建的 binary 不保證能在舊發行版跑，PyInstaller 產物也不是 manylinux 相容包。
- **macOS 的敵人是 Gatekeeper 不是打包工具。** Developer ID 簽章、hardened runtime、notarization、arm64/x86_64 雙架構，PyInstaller 一項都不替你解決。

---

## 四、結論：最優組合

**保留 Python 核心，不重寫語言。優化落在資料流與發行方式上。**

```
worklog/core     純標準庫，維持不引入第三方依賴（這是可打包性的根本保障）
worklog/cli      argparse，獨立可執行，不依賴 fastapi
apps/api         FastAPI + StaticFiles，直接內嵌前端 build 產物
apps/web         React + Vite，建完把 dist/ 交給 API 層
```

具體動作，按優先序：

1. **前端內嵌進後端。** 用 FastAPI 的 `StaticFiles` 服務 `apps/web/dist/`，並把 CORS 從「只允許 vite dev origin」放寬為同源。這一步消滅了「兩個終端機、兩套工具鏈、還要配對 port」的部署摩擦，是投入產出比最高的單一改動。
2. **改增量分析。** 依 `source_hash` 判斷哪些對話變更，只重算這部分；合併 `build_document` 的兩次全量載入。
3. **清掉宣告但未使用的依賴。** `typer`、`pydantic`、`pytest`、`httpx` 從 `pyproject.toml` 移除或改正（測試實際用 `unittest`）。這直接影響打包體積與建置時間。
4. **建立正式的 entry point 分層。** 現在 `apps/api/main.py` 用 `except ImportError` 讓 fastapi 變成「可選」，這對 CLI 開發方便，但若未來要當服務部署，必須改成正式的 package 分層，而不是繼續像附屬功能。
5. **發行方式分層處理：**
   - 自己在三台機器上用 → `uv tool install worklog`
   - 要發給不用 Python 的人 → 先用 PyInstaller **`one-dir`** 驗證三平台行為，**量過冷啟動**之後再決定要不要做 `onefile`
   - 若確定要做多人雲端 → 另建獨立的 server 佈署路徑（container / systemd），**不要把 PyInstaller 當成伺服器佈署單元**
6. **Tauri 只在 UI 明確成長為主要產品時再考慮。** 目前前端僅 170 行，引入 Rust 工具鏈與 Linux webkit2gtk 依賴，成本遠大於收益。

---

## 五、這個結論什麼情況下會錯

以下是推翻上述判斷所需的證據，出現任一項就該重新評估：

- 增量優化之後，Python 在**真實資料量**下仍達不到延遲或記憶體目標 —— 那時才輪到語言比較，且要拿量測數據比，不是拿「naive Python vs 假想的 Go」比
- 「離線、無 runtime、單檔」被確認為**硬性需求**，而不只是偏好
- UI 路線明確要求原生 shell（system tray、原生選單、離線視窗）
- 多人雲端已確定要做，而不只是遠景

還有一個前置問題目前沒有答案，它會改變整個建議：**這個工具是只給自己用，還是要發行給別人？** 使用者是工程師，還是一般使用者？如果答案是「我自己在三台機器上用」，那麼真正的瓶頸通常不是佈署，而是資料模型、SQLite migration、備份、以及 Windows / macOS 的路徑與 keyring 差異 —— 在那個情境下 `uv tool install` 比任何打包方案都正確。

---

## 六、趨勢查證紀錄

查證用的是 open-websearch MCP。**誠實說明：多數英文技術關鍵字回傳的是教學文或零結果，決策價值低**，因此以下區分「查到的」與「既有知識」。

**查到的現況錨點：**

- PyInstaller 現行版本 **6.22.3**，持續維護中
- Tauri 2 為現行穩定版本
- uv 為 Rust 寫成，已是 Python 環境與依賴管理的事實標準，可取代 pip / virtualenv / pyenv

**基於既有知識、未經本次查證確認：**

- PyOxidizer 已停止維護，不應再選用
- pydantic v2 核心為 Rust 實作的平台專屬 wheel
- PyInstaller 無法交叉編譯、Linux 產物受 glibc 版本約束
- Tauri 在 Linux 依賴系統 webkit2gtk，各發行版版本要求不一

上述未確認項若要據以投入工程，落地前應再核實。

本文件的架構判斷經過一輪對抗性審查：初版假設「保留 Python + 前端內嵌 + PyInstaller 單檔」，審查後修正為「PyInstaller 單檔並非已被證成的最佳解，`one-dir` 與 `uv tool install` 應優先」。

---

## 七、附錄：Claude 提問模式的語意檢討

本節與前六節的佈署架構問題無關，是另一個獨立任務的方法紀錄。記錄目的是留下「怎麼得出結論」的軌跡，而不只是結論本身。

分析日期：2026-10-17。

### 7.1 被問的問題

使用者原話：

> 我叫你檢查 claude sessions 是為了語意檢討我的所有對 claude 提問的需求，是不是 rea mcp 可以幫助，例如說我現在要新增或改一個 spring boot 功能，rea mcp 可以幫助之類的。

拆成兩個可回答的子問題：

1. REA MCP 能否成為「新增/修改 Spring Boot 功能」時的槓桿？
2. 這一個月對 Claude 的提問，有哪些模式性的缺口？

### 7.2 分析步驟

| 步驟 | 做了什麼 | 為什麼這樣做 |
| --- | --- | --- |
| 1 | 讀 `F:\Backup\REA.md` 全文，取得它自己的目標清單 | 使用者對工具的描述屬二手轉述，改以原始文件為準 |
| 2 | 比對目標清單與 Spring Boot 的射程 | REA 列出原生二進位、Go/Rust/WASM、JS/Electron、.NET、Android、網站、pcap、韌體、Flutter —— **無 Java** |
| 3 | 實測環境可行性，而非從 README 推論 | Node 實測 22.18.0，REA 要求 ≥22.19；Ghidra/IDA/Hopper 皆不在 PATH；Java 僅 1.8.0_171 |
| 4 | 轉向真正的問題：提問語意檢討 | 「檢查 session 標題與摘要」在 `history.jsonl` 中無對應結構 |
| 5 | 從 `history.jsonl` 取 767 筆有效提問做統計 | 40 個 session，2026-09-19 → 10-17 |
| 6 | **關鍵詞分群失敗**：50% 落在「其他」 | 詞表覆蓋不足，改用「每 session 首則」抽樣讀實際內容 |
| 7 | 對 125 個長 prompt（>200 字）做特徵標記 | 量化使用者自己寫過的規則，在實際提問中出現頻率 |
| 8 | 交叉對照 auto-memory 的事故紀錄 | 把統計缺口與真實損失建立因果，而不是只報百分比 |
| 9 | 掃描四個程式碼根目錄的 `.codegraph` | 驗證既有 CLAUDE.md 規則是否真的可觸發 |

步驟 6 是方法上的失敗點，值得單獨記下：**先用關鍵詞分群、再讀實際內容**的順序是錯的。先讀十則真實提問再設計分類軸，成本低得多。

### 7.3 資料來源與限制

| 來源 | 性質 | 限制 |
| --- | --- | --- |
| `~/.claude/history.jsonl` | 767 筆使用者輸入 | 只有 `display`（輸入），**無 Claude 的回應**，因此無法判斷提問是否被正確執行 |
| `~/.claude/projects/F--/memory/` | 7 筆事故與事實記憶 | 樣本少，因果屬使用者自述 |
| `F:\Backup\CLAUDE_sys_20260902.md` | 384 行行為規則草稿 | **整段期間未生效**（`~/.claude/CLAUDE.md` 只有 47 行 Codex 規則） |
| 本機官方 plugin `claude-md-management` | 品質標準 | Anthropic 官方，權威性高 |
| open-websearch MCP | 外部查證 | **本次全部失敗**（ECONNRESET / 0 結果），故無社群基準可比對 |

**未經本次查證確認的項：**社群對 CLAUDE.md 長度的普遍水位。搜尋管線當日不穩，因此本文件不引用任何外部數字。

### 7.4 五個發現

**發現 1：明確禁止項只佔長 prompt 的 9%，但兩次真實事故都源於「沒禁止」。**

125 個長 prompt 中，寫明「不要／先別／勿」者 12 個。對照記憶體：

- i18n 事件：未要求「測試資料一行不動」，switch/case 被改斷
- rebuild.bat 事件：未要求「先跑再說」，先加了一堆防禦性檢查才發現只是缺 proxy 設定

而寫得好的提問恰好都含禁止項：`解決但不要測試 git`、`先判斷不要做`、`不要影響目前正常的 relay.js`。**最佳實踐已存在，只是沒有成為習慣。**

**發現 2：「先判斷不要做」是已掌握的高價值句式，但只偶爾使用。**

實際出現過 `先判斷不要做`、`幫我判斷問題先不要調整`、`先判斷我的理解對不對`。此句式強制模型先給結論、不動手，直接對應舊規則 §1e。

**發現 3：Codex 協作規則幾乎未落地。**

767 則中僅 10 則提及 codex，長 prompt 裡趨近於零。代表跑腿活仍由使用者逐條手動餵送，委派並未真正發生。原因未查證——可能是規則繁瑣，也可能是對輸出不信任。

**發現 4：`.codegraph` 一個都沒建，相關 CLAUDE.md 規則目前是空轉。**

`Xylon_SourceCode` / `XtrackIService` / `Xtrack` / `Xylone` 四個根目錄掃描結果皆為 0。CLAUDE.md 中「有 `.codegraph/` 就用 `codegraph_explore`、不要 grep」在全部 codebase 上永不觸發。

**發現 5：Spring Boot 的最高槓桿是既有規則 §7c，不是新工具。**

§7c 的「參照對照模組」六步清單（確認 Controller 參數接收方式、前端呼叫方式、Service 分頁邏輯、Mapper 的 `jdbcType`、Vue 搜尋機制），並附 `AppF1UserController.listForPage()` 具體範例。此規則對反覆製作同型 list/page/upload 模組的後端工作，價值高於任何逆向工具。

### 7.5 這份結論什麼情況下會錯

- `history.jsonl` 只記錄輸入。若使用者的提問本身沒問題、問題在模型執行面，本分析會把缺口**歸因錯誤**
- 9% 的禁止項比例，可能反映「規則本該由 CLAUDE.md 自動生效，不必每次重打」。若規則已生效，這個數字就不是缺口而是正常設計。但本次查證顯示該規則檔**整段期間未生效**，故此辯護不成立
- 767 樣本集中於一個月、單一台機器、單一專案群。跨專案推論未經驗證

### 7.6 未決選項

| 選項 | 內容 | 價值判斷 |
| --- | --- | --- |
| A | 把 §7c 六步清單撈回，做成 `skill:spring-module-pattern` | 直接補 11% 的 Spring/Java 工作，槓桿最高 |
| B | 建自訂指令（如 `/guard 不要動測試資料`） | 一行補上發現 1 的缺口，不佔常駐 context |
| C | 決定 `.codegraph` 要不要建 | 建則規則生效，不建則該刪掉該行 |

三項皆未執行。

---

## 八、工作交接：NiuMaLog 僅存 fork 與 Claude/Codex 匯入修復

本節是給**下一個全新 session** 的接手文件。前七節是分析結論，本節是「目前做到哪裡、哪些是故意的、下一步是什麼」。

工作日期：2026-10-17（本節寫於 2026-10-19，服務與資料狀態已重新驗證）。

### 8.1 專案關係（容易搞混，先講清楚）

| 路徑 | 是什麼 |
| --- | --- |
| `F:\30590\SelfWork\WorkLog\PythonVersion\` | 本地副本，第一～六節的分析對象 |
| `F:\30590\SelfWork\WorkLog\README.md` | 第一～六節架構分析的原始寫入位置 |
| `git@github.com:johch3n611u/NiuMaLog.git` | **同一個專案的 fork**，remote 已設為 HTTPS |
| `F:\30590\SelfWork\NiuMaLog\` | 本次實際動手的 repo（本文件所在處） |

兩份代碼結構相同，但**本次所有修改都在 NiuMaLog，`PythonVersion` 一行未動**。

### 8.2 目前狀態（2026-10-19 實測）

| 項目 | 狀態 |
| --- | --- |
| git 分支 | `main...origin/main`，**8 個檔案已修改、尚未 commit** |
| 修改量 | +321 / -28 行 |
| 後端 8000 | **已停止**（`Connection refused`） |
| 前端 5173 | **已停止** |
| `apps/web/dist` | 已建置，可被 FastAPI 掛載 |
| SQLite `.worklog/worklog.db` | 477 會話 / 10,504 訊息 / 10,052 事件 |

改動清單（全部未 commit）：

```
M apps/api/main.py                        靜態檔掛載、自動開瀏覽器、events 改水位判斷
M apps/web/src/App.tsx                    API 位址改同源相對路徑
M apps/web/vite.config.ts                 dev proxy: /api -> 127.0.0.1:8000
M worklog/core/adapters/claude.py         新增原生 Claude Code JSONL 解析
M worklog/core/adapters/codex.py          新增原生 Codex rollout 解析
M worklog/core/analyzers/deterministic.py 空 marker 防護 + Windows 路徑 regex
M worklog/core/service.py                 fingerprint + refresh_events_if_stale
M worklog/core/storage.py                 meta 表、replace_events
?? launch.pyw                             雙擊啟動器（新增）
?? 啟動 Worklog.bat                        雙擊入口（新增）
?? example/                               cc-switch-main 參考資料（使用者放的）
?? SourceAnalysis.md                      本文件
?? worklog.egg-info/                      pip -e 產物，可忽略
```

### 8.3 怎麼啟動

```bash
# 方式一：雙擊 F:\30590\SelfWork\NiuMaLog\啟動 Worklog.bat
#   -> 用 pythonw 起後端（無終端機視窗）+ 自動開瀏覽器到 http://127.0.0.1:8000
#   -> 已在跑時不會重起第二個行程，只開瀏覽器

# 方式二：手動
cd F:/30590/SelfWork/NiuMaLog && ./.venv/Scripts/python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000

# 開發前端時才需要（Vite 8 要 Node >=22.12，預設 node 是 v18）
cd F:/30590/SelfWork/NiuMaLog/apps/web && export PATH="/d/nodejs:$PATH" && npm run dev -- --host 127.0.0.1 --port 5173
```

關掉自動開瀏覽器：設環境變數 `WORKLOG_NO_BROWSER=1`。

### 8.4 環境地雷（這台機器專屬，會再咬人）

| 事項 | 實測結果 | 影響 |
| --- | --- | --- |
| **Node 有三個** | `C:\Program Files\nodejs` = v18.15.0（**PATH 最前，預設抓到它**）；`D:\nodejs` = v22.18.0；`D:\nvm\v22.18.0` = v22.18.0 | Vite 8.3.4 / `@vitejs/plugin-react` 6.1.2 要求 `^20.19.0 \|\| >=22.12.0`，用預設 v18 起不來。臨時切換用 `export PATH="/d/nodejs:$PATH"`，**不要動系統 PATH** |
| **GitHub SSH 22 port 被封** | `Connection refused` | SSH 位址一律連不上。改用 HTTPS。fine-grained PAT 只適用於 HTTPS，對 SSH 完全無效 |
| **PyPI 只能走代理** | 不設代理直接 `Connection refused`；走代理約 9.5 秒/次 | `HTTP(S)_PROXY=http://127.0.0.1:15722` 已在環境中。pip 安裝慢是正常的，**不是掛掉**，不要中途殺掉重來 |
| git 2.36.0 | 不吃 `safe.directory` 萬用字元 | 與本次無關，但同機器其他 repo 會遇到 |
| Windows 主控台 | cp1252，印中文字會 `UnicodeEncodeError` | 跑分析腳本要加 `PYTHONIOENCODING=utf-8 PYTHONUTF8=1` |

**關於 SSH + PAT 的常見誤解（本次實際踩到）：** 使用者建了 fine-grained PAT，然後用 `git@github.com:...` 去 clone，失敗。原因是 PAT 走 HTTP header，SSH 認的是金鑰，兩套體系互不相通 —— 位址寫 SSH 就永遠不會用到 PAT。換成 `https://github.com/johch3n611u/NiuMaLog.git` 立刻成功。

### 8.5 修了什麼、為什麼

#### 主線：Claude / Codex 匯入完全無效

**症狀**：匯入 `C:\Users\30590\.codex` 與 `~/.claude/projects` 都回 `imported:0`，大量 `Unsupported source format`。

**根因**：兩個 adapter 的 `can_handle()` 都只認「檔名含 provider 名稱」或「payload 是 dict 且帶 provider marker」。但真實格式是：

- Claude Code：`~/.claude/projects/<編碼路徑>/<uuid>.jsonl` —— **檔名是 UUID，不含 "claude"**
- Codex：`~/.codex/sessions/YYYY/MM/DD/rollout-<時間戳>-<uuid>.jsonl` —— **檔名是 "rollout-" 開頭**
- 兩者的 JSONL 被 `read_payload()` 解析成 **list**，`isinstance(payload, dict)` 直接 False

→ 沒有任何 adapter 認領，全部被丟棄。

**格式細節**（下個 session 若要擴充适配器可直接用）：

```
Claude  record: { "type": "user"|"assistant"|"mode"|"ai-title"|...,
                  "message": {"role": "...", "content": str|[blocks]},
                  "timestamp", "cwd", "sessionId", "gitBranch", "uuid", ... }
          user content 是 str；assistant content 是 block 陣列（thinking/text/tool_use/tool_result）
          ai-title record 帶 aiTitle，可當會話標題

Codex   record: { "type": "session_meta"|"response_item"|"event_msg"|"world_state"|"turn_context",
                  "payload": {...}, "timestamp", "ordinal" }
          只有 type=="response_item" 且 payload.type=="message" 才是對話
          payload.role 為 developer/system 的是注入指令，不是工作內容
          session_meta.payload.cwd 是專案目錄
```

**修法**：各自新增 `_parse_native()` 走原生格式，並保留原本的通用匯出格式路徑 —— **`tests/fixtures` 一行未動**（它們是 `{provider, chat_messages:[...]}` 的通用匯出格式，代表格式契約）。

**成效**：Claude 113/113、Codex 18/18，零錯誤。

#### 連帶修掉的三個既有 bug

**Bug A — `/api/events` 只在「一個事件都沒有」時才重新分析**（`apps/api/main.py`）
原本 `if not storage.list_events(...): service.refresh_events()`。匯入 131 個會話後，因為 DB 裡還有先前測試留下的 5 筆事件，分析永遠不會重跑 → **使用者看到的是「匯入了但什麼都沒出現」**。
改法：加 `meta.analyzed_fingerprint` 水位（會話數 + 訊息數 + 最新 imported_at），資料有變才重算。實測首次 2.97s、之後 0.51s。

**Bug B — `save_events` 只 upsert 從不刪除**（`worklog/core/storage.py`）
事件 id = `stable_hash(message.id, project, event_type)`，project 推導一修正，id 就變，舊列永久殘留。新增 `replace_events()` 做整批取代；`event_overrides`（使用者手動編輯）不受影響。

**Bug C — 一個空的 `项目：` 會把整個會話的專案釘成空字串**（`deterministic.py`）
`analyze()` 先掃全體訊息建 `conversation_projects`，而 capture 群組 `[\w\-./一-龥 ]` **含空白** —— 只要會話裡有任何一則寫了 `项目：` 後面跟空白（程式碼、markdown 表格裡極常見），整段會話就變空專案。**2,602 筆事件受影響，修後歸零**。改為只記非空值。

**附帶修 — Windows 路徑在第一個反斜線斷掉**
同一個 regex 不含 `\`，`Project: F:\JavaWorkspace` 只抓到 `F`，952 筆事件專案變成 `'F'`。regex 字元類別加入 `\` 與 `:` 後變成 `F:\JavaWorkspace`。

### 8.6 驗證紀錄

| 項目 | 結果 |
| --- | --- |
| `python -m unittest discover -s tests` | **8/8 通過**（改動前後各跑一次） |
| 真實資料匯入（CLI 暫存 DB） | Claude 113/113、Codex 18/18、0 錯誤 |
| 真實資料匯入（走 `/api/import`） | Claude 112 imported、Codex 18 imported、0 錯誤 |
| 事件重新分析 | 5 → 9,934 → 10,052（後者是使用者後續再匯入的結果） |
| 空 project | 2,602 → **0** |
| 瀏覽器實測 | 時間線正確渲染，**console 零錯誤零警告** |
| `npm run build` | `tsc -b` + vite build 皆通過（`dist/` 已產出） |
| 雙擊啟動器 | 冷啟動路徑 exit 0；重複執行偵測既有實例不重起 |

### 8.7 已知未修的問題（按嚴重度）

**問題 1：專案提取規則太寬，UI 的 chips 區不可用（最該先處理）**
`#([\w\-]+)` 這條 tag 規則會把 markdown 標題、程式碼識別符都當成專案名。chips 區現在有幾百項，大量是雜訊：`getId`、`767676`、`agent-a9f7d74329f4e4813`、`00d4ff`、`888`、`999`。
這是**設計決定**所以當時沒擅自動。三個選項：
- (a) 只承認 `项目:` 標記，拿掉 `#tag` 規則
- (b) 保留 `#tag` 但過濾明顯不是專案的值（hex、UUID、純數字、camelCase 識別符）
- (c) 改用 `cwd` 欄位當專案來源 —— **adapter 已經存進 `metadata["cwd"]` 了**，但目前沒有任何程式碼讀取它。這才是真正的專案目錄

**問題 2：`refresh_events()` 全量重算**
10,504 筆訊息約 2.5–3.5 秒。水位記號已避免「每次請求都重算」，但匯入後第一次仍要全量。`conversations.source_hash` 已存在，可作為增量分析的鍵。

**問題 3：`generate()` 重複寫入**
`WorklogService.generate()` 與 `_save_document()` 各呼叫兩次 `storage.save_report()`（xlsx 檔案路徑產生後再存一次）。冗餘但無害。

**問題 4：`build_document()` 全量載入兩次**
`refresh_events()` 載一次，`storage.list_all_messages()` 又載一次當證據查表。證據查詢應改 `WHERE id IN (...)`。

**問題 5：宣告但未使用的依賴**
`pyproject.toml` 的 `typer`、`pydantic`、`pytest`、`httpx` 程式碼零引用（cli 用 argparse、domain 用 dataclass、測試用 unittest）。清掉可縮小打包體積與建置時間。

### 8.8 沒做的事（避免下個 session 重複浪費）

- **沒有 commit、沒有 push。** 依使用者規矩，修改留在工作區由他決定
- **沒有動 `PythonVersion/`**
- **沒有動 `tests/fixtures/`** —— 它們是格式契約，改了會掩蓋真實格式相容性問題
- **沒有實作 `example/cc-switch-main/session-manager.md` 的 PRD。** 那份文件的 FR-3（路徑探測可配置）與 6.1（`detect()/scanSessions()` 抽象）正是本次缺的東西 —— 目前 `can_handle()` 是靠猜路徑，不是正式的路徑探測。這是一個獨立規模的工作
- **沒有處理問題 1–5**（見 8.7）

### 8.9 下一步建議

1. **先修問題 1**（專案提取）。資料已經匯進來了，但 chips 區不可用讓時間線的價值打折。建議選 (c) 用 `cwd`，因為 adapter 已經存好資料，只是沒人讀
2. 然後決定要不要 commit。目前 8 個檔案混了三件事（前端內嵌、适配器修復、分析器修正），**建議拆成三個 commit**，各自可獨立 revert
3. 若要往 session-manager 方向走，先讀 `example/cc-switch-main/session-manager.md` 的 FR-1/FR-3/6.1，把「猜路徑」換成「配置驅動的路徑探測」

### 8.10 這個交接文件什麼情況下會過期

- 使用者已 commit 或已 revert —— 8.2 的 git 狀態立刻失效
- 服務被重新啟動 —— 8.2 的「已停止」失效（這是寫作當下的快照）
- 匯入更多資料 —— 8.2 的資料筆數失效
- `~/.claude` 或 `~/.codex` 的格式改版 —— 8.5 的格式說明失效，需重新實測確認

其餘（根因、修法、設計決定的理由）不隨時間改變。
