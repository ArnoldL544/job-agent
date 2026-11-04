# Job Agent v0.4.1 — 合并安全修复

基于 v0.4，**只替换 `resume_chunk_writer.py`**，外加更新和新增测试。不需要改 `resume_editor.py`、`run_screened_resumes.py`、`resume_selector.py`，也不需要改 API Key。`generate()` 的调用方式不变，返回结果多了两个字段：`entry_fallbacks`、`estimated_lines_saved`。

## 修了什么

| # | 问题 | v0.4.1 行为 |
|---|---|---|
| 1 | 合并时动作和归属可能被调换（例如 "Assisted" 被挪到 SVD 上，"Implemented" 被挪到数据验证上），机械校验检查不出来 | 以 Assisted / Supported / Participated / Contributed / Helped 等开头，或者含有 `under mentor guidance`、`only`、`planned`、`in progress` 等限定的 bullet，一律**不参与合并**。请求里会标记 `merge_eligible=false`，即使模型照样合并了，本地也会拒绝。另外，两条来源的开头动词**都必须保留**（v0.4 只要求保留其中一个） |
| 2 | `end-to-end`、`real-time`、`fine-tuned` 被拆成几个词，强结论检测没有生效；句尾的词会带上句号（`users.`） | 分词时保留连字符、去掉句尾句号。强结论改用正则匹配，`end to end` 这种不带连字符的写法也能识别 |
| 3 | 旧路径（没有达到 3 条的 Entry，走 v0.3.1 单条改写）允许删掉数字和技术名词 | `check_rewrite` 本身改为要求**数字和技术名词完全一致**，新旧两条路径都适用 |
| 4 | group 顺序不对会让整份草稿作废，浪费一次 API 调用 | 改为自动排序。如果某个 Entry 漏了 ID、重复 ID 或违规合并，**只把这个 Entry 退回原句**。跨 Entry 或未知的 ID 仍然直接终止 |
| 5 | 用"字符数 ≤ 95%"判断是否变短，可能出现合并了却一行都没省的情况 | 按每行约 95 字符估算 Word 行数：只有**至少节省 1 行**、且合并后不超过 3 行的合并才会被接受。报告里会写出每条合并"N 行 → M 行"，以及总共节省的行数 |
| 6 | 每次运行 `prepare()` 被调用 2～3 次；请求里同一份 bullet 发了两遍 | `prepare()` 只运行一次；请求里只发送 `source_entries`，节省 token |

## 安装（Windows PowerShell，项目根目录）

```powershell
cd "C:\Users\25051\Desktop\agent project"

# 1. 备份当前 v0.4 Writer 和测试
Copy-Item .\resume_chunk_writer.py .\resume_chunk_writer_before_v041.py
Copy-Item .\tests\test_chunk_composition_v04.py .\tests\test_chunk_composition_v04_before_v041.py

# 2. 解压
Expand-Archive -LiteralPath "$env:USERPROFILE\Downloads\JobAgent_ChunkCompose_v0.4.1.zip" -DestinationPath ".\_upgrade_v041" -Force

# 3. 替换 Writer，更新并新增测试
Copy-Item ".\_upgrade_v041\resume_chunk_writer.py" ".\resume_chunk_writer.py" -Force
Copy-Item ".\_upgrade_v041\tests\test_chunk_composition_v04.py" ".\tests\test_chunk_composition_v04.py" -Force
Copy-Item ".\_upgrade_v041\tests\test_chunk_writer_v041.py" ".\tests\test_chunk_writer_v041.py" -Force

# 4. 离线测试（不调用 OpenAI）
python -m unittest discover -s tests -p "test_chunk_*.py" -v
python -m unittest discover -s tests -v

# 5. 真实 JD 生成（会提示确认 API）
python .\run_screened_resumes.py --job-id 11651900 --chunk-tailored --force
```

回滚：

```powershell
Copy-Item .\resume_chunk_writer_before_v041.py .\resume_chunk_writer.py -Force
Copy-Item .\tests\test_chunk_composition_v04_before_v041.py .\tests\test_chunk_composition_v04.py -Force
```

> 注意：第 4 步如果你 `tests` 文件夹里的旧测试**直接断言了以下报错文字**，需要按下表更新（只有这两条报错文字改了）。如果旧测试本身就在断言"删掉数字的改写应该通过"，那正是这次修掉的漏洞，那条测试应该改为断言"会被拒绝"。
>
> | 旧文字 | 新文字 |
> |---|---|
> | `new or changed numbers` | `numeric evidence added or removed` |
> | `new named skill/technology` | `named technology added or removed` |

## 跑完要检查什么

打开新生成的 `.md` 报告：

1. 顶部的 `Estimated Word lines saved by merges` 是否 ≥ 1，再到 Word 里确认这段经历确实少了一行。如果估算结果总是偏多或偏少，调整文件开头的 `CHARS_PER_LINE`（默认 95）。
2. 每一条 `merged`：Source 1 和 Source 2 里每个独立的事实是否都还在？每个动词是否还挂在原来的那件事上？
3. 如果出现 `entry_fallback`：说明模型对这个 Entry 的输出结构有问题，已经退回原句，看一下 Validation 里写的原因即可。
4. 被拒绝的单条改写（`rejected`）比 v0.3.1 多是正常的：现在删掉数字或技术名词的改写会被拒绝。

## 已知限制

- 行数是**估算**值（textwrap 按字符数换行），不是 Word 的实际排版结果。v0.5 计划改成渲染 PDF 后实测。
- 合并后空出来的位置**仍然不会自动补位**，这部分留到 v0.5。
- 机械校验只能拦住"词丢失、词新增、归属受限的合并"，无法证明语义正确，仍然需要人工审核。

## 离线验证

用 v0.3.1 的 `resume_chunks.py` 和 `resume_selector.py` 在隔离环境中测试：20 项通过（v0.4 原有 4 项，其中 1 项按新行为拆成 2 项，加上新增 15 项）。另外把新增的 15 项拿到**旧 v0.4** 代码上跑，有 14 项失败，说明这些测试确实能拦住原来的问题；剩下 1 项是"正确的合并仍然要通过"的守护测试。没有在你的真实 API 账户上验证过。
