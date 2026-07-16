# Paper Notes Summary Schema

This document defines a faithful, evidence-aware reading note. It is a guide for reasoning, not a prose template to imitate. The output must begin with a coherent article guide before the detailed fields and section-by-section notes.

## 1. Choose the paper profile first

Set `paper_type` to one or more applicable values:

- `empirical`: observational, experimental, or qualitative evidence
- `theory`: formal model, conceptual argument, or propositions
- `method`: new algorithm, estimator, architecture, or analytical procedure
- `benchmark`: evaluation framework, benchmark, leaderboard, or stress test
- `dataset`: new dataset, annotation resource, corpus, or measurement instrument
- `survey`: literature review, taxonomy, meta-analysis, or position paper
- `system`: deployed system, application, or engineering pipeline
- `replication`: replication, reanalysis, or robustness study
- `other`: use only when none of the above fits

Use the profile to select relevant fields. Do not force a field that does not fit. For example, benchmark papers should describe task taxonomy, data provenance, split design, contamination controls, metrics, baselines, failure modes, and what the benchmark actually measures. Dataset papers should describe sampling, annotation protocol, quality control, coverage, bias, licensing, and intended use. Survey papers should distinguish coverage claims from the authors' interpretation.

## 2. Output schema

```json
{
  "schema_version": 4,
  "zotero_key": "",
  "generated_at": "",
  "model": "",
  "paper_type": ["empirical"],
  "keywords": [],
  "reading_guide": {
    "background": "",
    "question": "",
    "approach": "",
    "main_findings": "",
    "insight": "",
    "limitations": ""
  },
  "one_sentence_summary": "",
  "research_question": "",
  "contribution": "",
  "background_and_gap": "",
  "data_or_materials": "",
  "method_or_design": "",
  "results_or_claims": "",
  "benchmark_or_dataset_details": "",
  "limitations_and_threats": [],
  "reproduction_conditions": "",
  "interpretation": "",
  "relevance_to_my_work": "",
  "evidence_map": [],
  "uncertainties": [],
  "key_quotes": [],
  "open_questions": [],
  "custom_notes": ""
}
```

Fields may be empty or marked `不适用` when the paper type makes them irrelevant. Keep the schema stable, but tailor the content to the paper. `benchmark_or_dataset_details` is required for `benchmark` and `dataset` papers and may be empty otherwise.

All prose fields use **canonical Markdown source**, never HTML. Use standard Markdown such as `**bold**`, `*italic*`, `` `code` ``, `[label](https://example.com)`, and simple ordered or unordered lists. The HTML renderer converts this source for display while preserving it verbatim in JSON and edits files, so the same note remains portable to Markdown and future output formats.

`reading_guide` is the first-pass explanation of the article. It must read as a connected narrative for an intelligent non-specialist:

- `background`: existing understanding, concrete gap, and why the study is needed.
- `question`: the specific question, hypothesis, construction task, measurement task, or comparison.
- `approach`: how the authors answer the question. Emphasize mechanism for method papers, research design for empirical papers, and resource construction plus evaluation for benchmark/dataset papers. Prefer 2–5 numbered points when the paper has separable design elements.
- `main_findings`: the most important results, supported by selective numbers or evidence anchors. Prefer 2–5 numbered points when the paper has separable findings.
- `insight`: what the results clarify or change, distinguishing author interpretation from independently supported inference.
- `limitations`: the most consequential boundary, threat, missing evidence, or alternative explanation.

Write each field concisely. `background`, `question`, `insight`, and `limitations` normally use short paragraphs. For `approach` and `main_findings`, prefer numbered points whenever the content can be divided without losing the argument. Use this exact pattern, one point per line: `1. **短而明确的结论**：用两三句解释它如何做、发现了什么或为什么重要。` The bold lead should state the point itself, while the explanation should be understandable but brief. Use a normal short paragraph only when a list would make the logic artificial or fragmentary. Do not repeat the same claim across fields. The guide should establish the paper's argument before the detailed fields are read.

`evidence_map` uses:

```json
[{"claim":"", "evidence":"Table 2, p. 7", "status":"reported"}]
```

Allowed statuses are `reported`, `supported_inference`, and `speculation`. Use `uncertainties` for missing information, unresolved alternative explanations, and claims that cannot be checked from the available materials.

## 3. Writing rules

1. Default language is Chinese. Keep quotation text in its source language.
2. Summary generation may use only text extracted by the Python pipeline: metadata/abstract, `section_text.json`, `sections.json`, and `annotations.json`. Do not open, inspect, OCR, describe, or infer from PDF image pixels. Figure manifests and extracted images are for the rendered paper page only, not LLM input.
3. Build `reading_guide` before detailed fields. Start with the paper's own question, design, and evidence; critique comes after reconstruction.
4. Adapt the narrative to the paper profile: method papers foreground the bottleneck, mechanism, validation, and operating conditions; empirical papers foreground question, design, findings, and competing explanations; benchmark/dataset papers foreground measurement gap, construction choices, evaluation, and capability or coverage insight; theory papers foreground assumptions, propositions, derivation, and scope; survey papers foreground review question, coverage, organizing framework, and synthesis.
5. Use concrete nouns, numbers, comparisons, sample sizes, metrics, and page/table references whenever available.
6. Separate three layers: what the authors report, what the evidence supports, and what remains conjectural. Do not present an inference as a finding or an author interpretation as a demonstrated mechanism.
7. Do not invent details absent from the extracted text, abstract, annotations, or metadata. If the material is insufficient, say so. A missing `section_text.json` with an available PDF is a workflow error, not permission to read the PDF directly.
8. Avoid promotional language such as “重大突破”“彻底改变”“颠覆”“强有力地证明” unless the paper and evidence genuinely justify it.
9. Avoid canned openings and repeated evaluative formulas such as “本文最重要的贡献是……”, “这不仅……而且……”, or “从……角度来看……”. Vary sentence structure naturally.
10. **Do not use contrast constructions of the form “不是……而是……”, “并非……而是……”, “not X but Y”, “rather than X, Y”, or close variants.** Express the relationship with direct sentences, evidence, or a qualified comparison.
11. Do not use first-person markers as stance labels: avoid “我认为”“在我看来”“I think”, “In my opinion”, “My read is”, “we can see”, and similar formulas. State the judgment directly and support it.
12. Markdown is allowed in all prose fields. Use `**double asterisks**` to emphasize important concepts, mechanisms, metrics, caveats, and paper-specific terms. Keep emphasis selective: normally 2–6 emphasized spans per substantial field, never whole paragraphs.
13. Every substantial prose field should contain meaningful emphasis where it improves scanability. Do not add bold merely to satisfy a quota; short fields may remain unbolded.
14. Long prose should be concise. Use one paragraph for a compact field and two or three only when the paper has genuinely distinct claims. Lists belong in arrays.
15. In the `论文速览` block, make `approach` and `main_findings` easy to scan: prefer 2–5 numbered points, each beginning with a bold, specific lead and followed by roughly two or three short sentences of explanation. Do not use a list merely to restate headings; choose a normal paragraph when the paper has only one inseparable method or conclusion.

## 4. Field guidance

- `one_sentence_summary`: question, intervention, and main finding in one sentence.
- `research_question`: the question or claim the paper actually investigates.
- `contribution`: what is newly supplied, measured, organized, or demonstrated.
- `background_and_gap`: only the context needed to understand the gap; avoid a miniature literature review.
- `data_or_materials`: source, sample, unit of analysis, collection period, inclusion rules, and missingness when known.
- `method_or_design`: the mechanism, identification strategy, model, protocol, or evaluation design. Explain how it connects inputs to claims.
- `results_or_claims`: headline results with uncertainty, effect sizes, confidence intervals, ablations, subgroup patterns, or qualitative themes as applicable.
- `benchmark_or_dataset_details`: task taxonomy, splits, baselines, metrics, contamination or leakage controls, annotation agreement, coverage, licensing, and failure modes as relevant.
- `limitations_and_threats`: concrete threats to validity, coverage, measurement, causal interpretation, external validity, or reproducibility.
- `reproduction_conditions`: dependencies, data access, annotation or expert labor, compute, implementation details, and likely bottlenecks. State only what is supported.
- `interpretation`: a short synthesis of what the evidence establishes, what it suggests, and what remains unresolved.
- `relevance_to_my_work`: use the project's current memory and name a specific research question, design choice, dataset decision, or measurement problem. If the connection is weak, say so.

## 5. Quotes and attribution

`key_quotes[].text` must be copied verbatim from `papers/<KEY>.annotations.json`. Never reconstruct or polish a quote. If there are no annotations, use `[]`. Include page, color, and a short explanation only when available.

Before finalizing, check: every strong claim has a source or an explicit status in `evidence_map`; every missing input appears in `uncertainties`; no forbidden contrast construction or first-person stance formula remains; and the output does not contain generic filler.

## 6. Section-by-section analysis

After writing the main summary, create `papers/<KEY>.sections.json` from every section in `papers/<KEY>.section_text.json`:

```json
{
  "zotero_key": "",
  "generated_at": "",
  "sections": [
    {
      "heading": "Introduction",
      "number": "1",
      "page": 2,
      "level": 2,
      "summary": "该节提出……**研究缺口**……",
      "analysis": "这一论证依赖……**关键限制**……"
    }
  ]
}
```

Include all extracted sections, including Methods and supplementary methodological sections when present. Copy `number` from `section_text.json` when present; leave it empty for unnumbered sections such as Abstract. Preserve source order: a parent such as `2` must precede `2.1`, `2.2`, and `2.3`, and `2.2` must never precede `2`. Never fabricate a section when extraction returned no text. If a section has too little usable text, preserve its heading and explain the limitation in `analysis`.

Set `level` from the source number: a top-level numbered section such as `4` uses `level: 2`; a direct subsection such as `4.1` uses `level: 3`; deeper levels increase accordingly. Do not assign the same level to a parent and its numbered child.

## 7. After generating

Write the JSON to `papers/<KEY>.summary.json`, then run:

```bash
python3 scripts/build_paper_html.py --key <KEY>
python3 scripts/build_dashboard.py
```
