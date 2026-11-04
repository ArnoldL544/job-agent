# Job Agent chunk-v0.5 — 按一页篇幅动态选择内容

基于 v0.4.1。运行方式不变：仍然是 `run_screened_resumes.py --chunk-tailored`，仍然只调用 **一次** API。`generate()` 的调用方式也不变，返回结果里多了几个字段：`final_bullets`、`refilled`、`dropped_for_space`、`page_count`、`page_check`。

## 改了什么

| # | 之前 | chunk-v0.5 |
|---|---|---|
| 1 | 固定最多 4 段经历、8 条 bullet，页面底部空了大约 1/4 | **按估算的页面高度填满一页**：先放和 JD 相关的技术 bullet；与 JD 关系不大的项目先最多给 2 条，然后让活动/奖项补位，最后剩下的空间再回给技术内容。实习经历始终保留 |
| 2 | 活动、奖项两个板块总是被整段删掉 | 页面有空间时，作为补位放进去，**按 Master 里的原顺序放**，所以第一条（说明项目或职务的那条）会最先出现 |
| 3 | 合并后空出来的位置一直空着 | 合并或改写之后，用 Master 里**未选中的原句**补上，不再调用模型。被合并掉的原句不会被重复补回 |
| 4 | `rest`、`model`、`networking`、`network`、`interactive` 这类普通英文词会让 JD 的所有方向都被判成相关 | 这些词不再触发误判；公司介绍、福利、EEO 等段落不计入；方向权重改成按出现频率和所在段落加权（要求段 > 职责段 > 其他） |
| 5 | 解析器认不出 `CAMPUS LEADERSHIP ACTIVITIES` 这样的标题 | 改为按关键词识别标题（LEADERSHIP / ACTIVITIES / AWARD / PROJECT…） |
| 6 | 只能估算是否超过一页 | 生成后**实际渲染并数页数**：优先用 Word（需要 pywin32），其次用 LibreOffice。如果超过一页，自动删掉价值最低的一条再重新生成 |

### 行高估算是怎么校准的

我用你的 `Resume_Arnold Li.docx` 做了实测：Cambria 11pt、单倍行距，每行 12.65pt，bullet 文字区宽约 482pt。代码里内置了 Cambria 的字符宽度表，模拟 Word 的换行，**不需要你电脑上有额外的字体文件**。在 3 份实际渲染的简历上，估算高度和真实高度相差都不到 1pt。

## 新增和修改的文件

| 文件 | 说明 |
|---|---|
| `resume_layout.py` | **新增**：页面空间模型和页数检查 |
| `resume_selector.py` | 修改：按页面选择内容、JD 降噪、方向权重分级。不传 `page_budget` 时，**旧的固定条数模式行为不变** |
| `resume_chunks.py` | 修改：标题按关键词识别 |
| `resume_chunk_writer.py` | 修改：使用按页面选择、合并后补位、超页自动删减 |
| `chunk_v05_preview.py` | **新增**：离线预览，**不调用 API** |
| `tests/test_chunk_v05.py` | 新增 13 项测试 |
| `tests/test_chunk_composition_v04.py`、`tests/test_chunk_writer_v041.py` | 只加了一行：测试运行时不启动 Word |

`resume_editor.py`、`resume_writer.py`、`run_screened_resumes.py`、前端都**不用改**。

## 安装（Windows PowerShell，项目根目录）

```powershell
cd "C:\Users\25051\Desktop\agent project"

# 1. 备份
$b = "_backup_before_v05"; New-Item -ItemType Directory -Force $b | Out-Null
Copy-Item resume_selector.py, resume_chunks.py, resume_chunk_writer.py $b
Copy-Item tests\test_chunk_composition_v04.py, tests\test_chunk_writer_v041.py $b

# 2. 解压并复制
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\JobAgent_chunk-v0.5.zip" -DestinationPath ".\_upgrade_v05" -Force
Copy-Item ".\_upgrade_v05\*.py" . -Force
Copy-Item ".\_upgrade_v05\tests\*.py" .\tests\ -Force

# 3. （建议）安装 pywin32，让程序可以调用 Word 精确检查页数
python -m pip install pywin32

# 4. 离线测试（不调用 OpenAI，也不会启动 Word）
python -m unittest discover -s tests -v

# 5. 离线预览（不调用 API）：看选了哪些内容、是否一页
python chunk_v05_preview.py --job-id 11651900

# 6. 正式生成（会提示确认 API）
python .\run_screened_resumes.py --job-id 11651900 --chunk-tailored --force
```

回滚：

```powershell
Copy-Item .\_backup_before_v05\resume_*.py . -Force
Copy-Item .\_backup_before_v05\test_*.py .\tests\ -Force
Remove-Item resume_layout.py, chunk_v05_preview.py, tests\test_chunk_v05.py
```

## 跑完要看什么

1. **预览（第 5 步）的终端输出**：每段经历前面的 `[***.]` 表示哪几条被选中。`Rendered pages` 应该是 1。如果显示 `not checked (none available)`，说明 pywin32 没装好，只能用估算。
2. **正式生成的 `.md` 报告末尾**有一节 `Page fit (chunk-v0.5)`：
   - `Rendered page count (Microsoft Word): 1`
   - `Refilled…`：合并后补上了哪几条原句
   - `Dropped…`：为了控制在一页内删掉了哪几条
3. **在 Word 里打开生成的 docx**：确认是一页，底部空白不超过两三行。

## 注意

- 这次的 `resume_selector.py` 和 `resume_chunks.py` 是基于你之前发给我审阅的那个版本改的。如果之后你在本地又改过这两个文件，替换前告诉我，我帮你合并。
- 用 Word 检查页数时，会在后台开一个隐藏的 Word 进程，不会影响你已经打开的文档，每次大约需要几秒。如果想跳过这一步，先运行 `$env:JOB_AGENT_VERIFY_PAGES="0"` 再生成。
- `run_screened_resumes.py --chunk-preview` 如果是直接调用 `select_chunks(master, jd)`，用的还是旧的固定条数模式，只有 JD 降噪这部分会生效。想看新的按页面选择效果，请用 `chunk_v05_preview.py`。
- 补位用的都是 Master 里的原句，不经过模型润色。所以 `.md` 报告里这些条目会标为 `refill`，内容和原句完全一样。
- Word 换页的检查代码在我这边没法实际运行（没有 Word），只验证过 LibreOffice 那条路径。如果 Word 检查出错，程序会自动回退到估算，不会因此失败。

## 离线验证

在隔离环境中：33 项测试全部通过（v0.4 原有 5 项、v0.4.1 的 15 项、v0.5 新增 13 项）。在你的真实 Master（加上 VADER/LDA 那条）上用两个示例 JD 端到端跑过：
- **前端 JD**：13 条技术 bullet 全部放入，其中 1 条合并，最后剩 12 条，LibreOffice 渲染为 1 页，底部约剩 1.6 行
- **数据分析 JD**：Amazon 4 条，另外三个项目各 2 条，加上 URCSA 1 条，渲染为 1 页

没有用你的真实 API 跑过。
