<input type="checkbox" id="lang-switch" class="lang-switch">
<label for="lang-switch" id="lang-label">🌐 中文 / English</label>

<style>
.lang-switch { position: absolute; opacity: 0; pointer-events: none; }
#lang-label {
  display: inline-block;
  cursor: pointer;
  font-weight: 600;
  padding: 6px 14px;
  margin: 4px 0 18px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #f8fafc;
  color: #334155;
  user-select: none;
}
#lang-label:hover { background: #eef2f7; }
/* Default: show Chinese, hide English */
.lang-en { display: none; }
/* Toggled: show English, hide Chinese */
#lang-switch:checked ~ .lang-en { display: block; }
#lang-switch:checked ~ .lang-zh { display: none; }
</style>

<div class="lang-zh">

# paper-notes

> **We Build Your Research Sense** — 把每一篇文献，都读成你的研究直觉。

一个基于 [Zotero](https://www.zotero.org/) 的论文精读工作流 skill。它维护一份人工精选的精读清单，抓取 PDF 高亮与笔记，把每篇论文渲染成**可编辑**的 HTML 页面，并汇总成一个带历史阅读日历的阅读仪表盘。正文由 Python 从 PDF 提取为文本，LLM 只读取文本，不读取 PDF 图片。

> 如果你在 GitHub 等不支持交互式切换的查看器中打开本文件，中英文两段会同时显示——直接向下滚动即可阅读对应语言。

## 特性

- **Zotero 同步**：通过配套的 `zotero` 技能抓取论文元数据、PDF 高亮与笔记（填补了 `zotero.py` 无法解析 Zotero 6+ 标注类型的空白）。
- **可编辑 HTML 精读页**：每篇论文生成一页可编辑的证据导向结构化摘要，支持 Markdown 段落和选择性加粗。
- **正文文本管线**：添加或刷新论文时自动提取 `section_text.json`；正文抽取失败会阻止完整笔记生成。
- **章节总结与分析**：根据 Python 提取的章节文本生成 `sections.json`，保留原文编号并进行父子章节排序校验。
- **阅读仪表盘**：按 Zotero 收藏夹分组，支持标签子筛选，并带历史阅读热力图/日历。
- **三种主题色**：玫瑰红 / 绿 / 蓝，可一键切换并记忆。
- **零外部依赖（核心脚本）**：除图提取需要 PyMuPDF 外，其余脚本仅用 Python 标准库；Web 字体随技能自托管，离线可用。
- **首次初始化向导**：首次调用时三问（语言 / 主题色 / 是否连接 Zotero），未初始化时代码层拒绝 `add`。
- **可脱离 Zotero 运行**：选择不连接 Zotero 时，可手动上传 PDF 完成精读，仪表盘隐藏热力图等依赖 Zotero 的模块。

## 安装

```bash
# 将 skill 复制到产品提供的 skills 目录
cp -R skill/paper-notes "$SKILLS_DIR/paper-notes"
```

前置条件：

- 设置环境变量 `ZOTERO_API_KEY` 与 `ZOTERO_USER_ID`（与 `zotero` 技能共用，在 https://www.zotero.org/settings/keys/new 创建）。
- 在产品提供的 skills 目录中安装或放置配套的 `zotero` skill，供 `paper-notes` 调用 `zotero.py`。
- 图提取需要 PyMuPDF：`pip install pymupdf`（技能会自动解析可用的解释器）。

## 快速开始

```bash
cd <你的项目目录>
# 首次：初始化（语言 / 主题色 / 是否连 Zotero）
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py init \
  --language zh --accent blue --connect-zotero yes

# 添加论文
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py add --key <ZOTERO_KEY>

# 生成仪表盘
python3 .codex/skills/paper-notes/scripts/build_dashboard.py
```

输出位于当前工作目录的 `outputs/paper-notes/`：
`dashboard.html`、`papers/<KEY>.html`、各类 `.json` 缓存。

## 致谢

本技能的**结构化笔记生成模块**在设计上借鉴了 [paper-reader-heilmeier](https://github.com/RealZYZhang/paper-reader-heilmeier) 这一优秀技能的思想（以 Heilmeier 问答框架组织论文精读笔记）。在此对其作者表示感谢。

## 许可

本技能按原样提供，供个人学习与使用。

</div>

<div class="lang-en" style="display:none">

# paper-notes

> **We Build Your Research Sense**

A Zotero-based paper close-reading skill. It maintains a hand-curated reading list, pulls PDF highlights and notes, extracts searchable body text with Python, renders each paper as an **editable** HTML page, and aggregates everything into a reading dashboard with a historical reading calendar. The LLM reads extracted text only; PDF images are never used as model input.

> If you are viewing this file in a renderer that does not support interactive toggling (e.g. GitHub), both language sections are shown — just scroll down to read the one you prefer.

## Features

- **Zotero sync** — fetches paper metadata, PDF highlights and notes via the companion `zotero` skill (filling the gap where `zotero.py` cannot parse Zotero 6+ annotation item types).
- **Editable HTML reading pages** — each paper gets an evidence-aware structured summary with Markdown paragraphs and selective bold emphasis.
- **Full-text extraction pipeline** — `section_text.json` is generated automatically; failed extraction blocks complete note generation.
- **Section analysis** — `sections.json` preserves source numbering and validates parent/child ordering.
- **Reading dashboard** — grouped by Zotero collections with tag sub-filters and a historical reading heatmap/calendar.
- **Three theme accents** — rose / green / blue, switchable and remembered.
- **Zero external dependencies (core scripts)** — everything but figure extraction uses the Python standard library; web fonts are self-hosted with the skill for offline use.
- **First-run init wizard** — three setup questions on first call (language / accent / connect-to-Zotero); `add` is refused by code until initialized.
- **Zotero-free mode** — when not connected, you can still add papers by uploading a local PDF; dashboard hides Zotero-dependent modules.

## Installation

```bash
# Copy the skill into the product-provided skills directory
cp -R skill/paper-notes "$SKILLS_DIR/paper-notes"
```

Prerequisites:

- Set the `ZOTERO_API_KEY` and `ZOTERO_USER_ID` environment variables (shared with the `zotero` skill; create a key at https://www.zotero.org/settings/keys/new).
- Place the companion `zotero` skill in the product-provided skills directory so `paper-notes` can call `zotero.py`.
- Figure extraction needs PyMuPDF: `pip install pymupdf` (the skill auto-resolves a capable interpreter).

## Quick start

```bash
cd <your project directory>
# First run: initialize (language / accent / connect-to-Zotero)
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py init \
  --language en --accent blue --connect-zotero yes

# Add a paper
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py add --key <ZOTERO_KEY>

# Build the dashboard
python3 .codex/skills/paper-notes/scripts/build_dashboard.py
```

Outputs land in `outputs/paper-notes/` under the current working directory:
`dashboard.html`, `papers/<KEY>.html`, and various `.json` caches.

## Acknowledgments

The **structured note-generation module** of this skill draws on the ideas of the excellent [paper-reader-heilmeier](https://github.com/RealZYZhang/paper-reader-heilmeier) skill (which organizes close-reading notes with the Heilmeier catechism). Credit to its author.

## License

Provided as-is for personal learning and use.

</div>
