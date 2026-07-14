# paper-notes

[English version](README_EN.md)

> **We Build Your Research Sense** — 把每一篇文献，都读成你的研究直觉。

一个基于 [Zotero](https://www.zotero.org/) 的论文精读工作流 skill。它维护人工精选的精读清单，抓取 PDF 高亮与笔记，把每篇论文渲染成可编辑的 HTML 页面，并汇总成带历史阅读日历的阅读仪表盘。正文由 Python 从 PDF 提取为文本，LLM 只读取文本，不读取 PDF 图片。

## 特性

- **Zotero 同步**：通过配套的 `zotero` 技能抓取论文元数据、PDF 高亮与笔记。
- **可编辑 HTML 精读页**：生成证据导向的结构化摘要，支持 Markdown 和 LaTeX。
- **正文文本管线**：自动提取 `section_text.json`，抽取失败会阻止完整笔记生成。
- **章节总结与分析**：生成 `sections.json`，保留原文编号并校验父子章节顺序。
- **阅读仪表盘**：按 Zotero 收藏夹分组，支持标签筛选和历史阅读热力图。
- **三种主题色**：玫瑰红、绿、蓝，可切换并记忆。
- **可脱离 Zotero 运行**：可手动上传 PDF，仪表盘会隐藏 Zotero 依赖模块。

## 安装

```bash
cp -R skill/paper-notes "$SKILLS_DIR/paper-notes"
```

前置条件：设置 `ZOTERO_API_KEY` 和 `ZOTERO_USER_ID`；图提取需要 PyMuPDF。

## 快速开始

```bash
cd <你的项目目录>
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py init \
  --language zh --accent blue --connect-zotero yes
python3 .codex/skills/paper-notes/scripts/manage_reading_list.py add --key <ZOTERO_KEY>
python3 .codex/skills/paper-notes/scripts/build_dashboard.py
```

输出位于当前工作目录的 `outputs/paper-notes/`。

## 致谢

结构化笔记生成模块在设计上借鉴了 [paper-reader-heilmeier](https://github.com/RealZYZhang/paper-reader-heilmeier) 的思想。

## 许可

本技能按原样提供，供个人学习与使用。
