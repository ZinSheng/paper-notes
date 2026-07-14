<div align="center">

# paper-notes

[![GitHub stars](https://img.shields.io/github/stars/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/network/members)
[![GitHub issues](https://img.shields.io/github/issues/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/issues)
[![License](https://img.shields.io/github/license/ZinSheng/paper-notes?style=flat-square)](LICENSE)

**A reusable, evidence-first workflow for close-reading research papers.**

*Zotero · PDF annotations · Editable HTML notes · Reading dashboard*

[English](README.md) · [中文](README_ZH.md)

</div>

---

> **We Build Your Research Sense** — 把每一篇文献，都读成你的研究直觉。

`paper-notes` 是一个面向 AI agent 的论文精读工作流 skill。它维护人工精选的精读清单，抓取 PDF 高亮与笔记，把每篇论文渲染成可编辑的 HTML 页面，并汇总成带历史阅读日历的阅读仪表盘。正文由 Python 从 PDF 提取为文本，模型只读取文本，不读取 PDF 图片。

## 特性

- **Zotero 同步**：通过配套的 `zotero` 技能抓取论文元数据、PDF 高亮与笔记。
- **可编辑 HTML 精读页**：生成证据导向的结构化摘要，支持 Markdown 和 LaTeX。
- **正文文本管线**：自动提取 `section_text.json`，抽取失败会阻止完整笔记生成。
- **章节总结与分析**：生成 `sections.json`，保留原文编号并校验父子章节顺序。
- **阅读仪表盘**：按 Zotero 收藏夹分组，支持标签筛选和历史阅读热力图。
- **三种主题色**：玫瑰红、绿、蓝，可切换并记忆。
- **可脱离 Zotero 运行**：可手动上传 PDF，仪表盘会隐藏 Zotero 依赖模块。

## 为什么值得使用

- **证据优先**：摘要和章节分析以抽取的正文、元数据和标注为输入，区分事实、推断和不确定性。
- **可持续编辑**：生成的 HTML 页面支持浏览器内编辑、自动保存、JSON 导入导出和文件夹同步。
- **可复现**：清单、摘要、章节文本、标注和用户编辑均以独立文件保存，便于备份与版本管理。
- **灵活连接**：可连接 Zotero，也可在无 Zotero 环境下手动导入本地 PDF。

## 安装

```bash
git clone https://github.com/ZinSheng/paper-notes.git
cd paper-notes
```

将 `skills/paper-notes/` 复制到支持 `SKILL.md` 技能目录的 agent runtime 中：

```bash
cp -R skills/paper-notes <your-skills-directory>/paper-notes
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

## 许可

本技能按原样提供，供个人学习与使用。
