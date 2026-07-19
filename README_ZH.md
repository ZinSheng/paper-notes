<div align="center">

# paper-notes

[![GitHub stars](https://img.shields.io/github/stars/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/network/members)
[![GitHub issues](https://img.shields.io/github/issues/ZinSheng/paper-notes?style=flat-square)](https://github.com/ZinSheng/paper-notes/issues)
[![License](https://img.shields.io/github/license/ZinSheng/paper-notes?style=flat-square)](LICENSE)

**一个把文献阅读沉淀为研究直觉的论文精读 skill。**

*Zotero 同步 · 论文速览 · 逐段精读 · 可编辑笔记 · 阅读仪表盘*

[English](README.md) · [中文](README_ZH.md)

</div>

---

> **We Build Your Research Sense** — 把每一篇文献，都读成你的研究直觉。

`paper-notes` 是一个面向 AI agent 的论文精读工作流 skill：从 Zotero 一键同步收藏夹、论文元数据、PDF 高亮和笔记；从正文中提炼论文框架与核心结论；再将逐段阅读笔记、与自身研究的关联分析和阅读历史，沉淀为可持续编辑的本地知识资产。

## 你能获得什么

- **一键同步 Zotero**：拉取 collections、论文元数据、PDF 高亮与笔记，把已有的文献库直接带入精读流程。
- **一页速览论文**：自动提炼要点、论文框架与核心结论，先建立全局理解，再决定从哪里深入。
- **逐段精读原文**：围绕原文生成阅读笔记，让长论文的细读有清晰抓手。
- **连接到自己的研究**：分析论文与你的研究问题、方法和方向的相关性，把“读过”变成可积累的 research sense。
- **阅读 Dashboard**：Dashboard 按 Zotero 收藏夹汇总论文列表、标签筛选、阅读记录与历史热力图。
- **把笔记真正留下来**：每篇精读页都可在浏览器中直接编辑、自动保存，并可同步 `.edits.json` 回本地文件夹。

## 特性

- **证据优先的文本管线**：从 PDF 提取正文到 `section_text.json`；提取失败会阻止完整笔记生成。模型读取抽取文本，而非 PDF 图片。
- **结构化精读输出**：生成论文速览、章节分析与逐段笔记；`sections.json` 保留原文编号并校验父子章节顺序。
- **Markdown + LaTeX**：所有笔记字段支持富文本与 MathJax 实时公式渲染。
- **图表提取与查看**：用 PyMuPDF 提取 PDF 嵌入图像、过滤小图和低清图，并以 Lightbox 查看原始分辨率。
- **可编辑、可导出、可复现**：支持浏览器编辑、localStorage 自动保存、JSON 导入导出和文件夹同步；清单、摘要、章节、标注和用户编辑均独立存储。
- **个性化阅读体验**：玫瑰红、绿、蓝三种主题色可一键切换，并按论文记住偏好。
- **可完全离线使用**：不连接 Zotero 也能手动上传本地 PDF 生成精读页；仪表盘自动隐藏依赖 Zotero 的模块。

## 安装

```bash
git clone https://github.com/ZinSheng/paper-notes.git
cd paper-notes
```

将 `skills/paper-notes/` 复制到支持 `SKILL.md` 技能目录的 agent runtime 中：

```bash
cp -R skills/paper-notes <your-skills-directory>/paper-notes
```

使用 Zotero 时，需设置 `ZOTERO_API_KEY` 和 `ZOTERO_USER_ID`；图表提取需要 PyMuPDF。

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
