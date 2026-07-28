# Paper Reviewer 多角色审稿系统设计文档

> **Created**: 2026-07-11
> **Author**: Yechen
> **Status**: Design Phase
> **Source**: 基于 academic-paper-reviewer v1.9.1 的 prompt 工程与流程设计

---

## 1. 目标

将现有单流程 Essay Grading System（Reviewer.py）改造为**多角色独立审稿系统**。新系统模拟国际期刊同行评审流程：自动识别论文领域、配置审稿团队、5 个审稿人从不同视角独立评审、最终由编辑综合做出决定并输出修订路线图。

## 2. 核心设计决策

### 2.1 技术架构
- **编排框架**：保留 LangGraph（StateGraph），节点为独立 Agent
- **Agent 实现**：每个审稿人为独立节点，拥有专属 system prompt 和输出 schema
- **并行执行**：5 个审稿人节点并行运行（LangGraph 支持并行分支）

### 2.2 评分体系
- **5 个核心维度**（加权计算最终分数）：
  - 原创性 (20%)
  - 方法严谨性 (25%)
  - 证据充分性 (25%)
  - 论证连贯性 (15%)
  - 写作质量 (15%)
- **2 个可选维度**（分别由 R2 和 R3 侧重报告，不纳入加权公式）：
  - 文献整合（R2 侧重）
  - 影响力（R3 侧重）
- **评分标度**：每个维度 0-100，带行为指标锚定

### 2.3 审稿团队（5 人 + 1 综合）

| # | 角色 | 焦点 | 输出 |
|---|------|------|------|
| 0 | Field Analyst | 领域分析 + 审稿团队配置 | Reviewer Configuration Cards |
| 1 | EIC | 期刊匹配度、原创性、整体质量 | EIC Review Card |
| 2 | Methodology Reviewer | 研究设计、统计有效性、可重复性 | Methodology Review Card |
| 3 | Domain Reviewer | 文献覆盖、理论框架、领域贡献 | Domain Review Card |
| 4 | Perspective Reviewer | 跨学科连接、实践影响、挑战假设 | Perspective Review Card |
| 5 | Devil's Advocate | 核心论点挑战、逻辑谬误、最强反证 | Stress-Test Report |
| 6 | Editorial Synthesizer | 综合全部报告，做出决定 | Editorial Decision + Revision Roadmap |

### 2.4 输出语言
- **默认输出中文**：无论论文原文是中文还是英文，审稿报告一律使用中文输出
- 学术术语保持英文原文（不翻译）
- 用户可通过参数显式指定输出语言（`--language zh/en`）

---

## 3. 状态定义

```python
class ReviewState(TypedDict):
    # ── 输入 ──
    paper: str
    paper_title: str
    paper_language: str                   # "zh" / "en"（自动检测或用户指定）

    # ── Phase 0: 领域分析 ──
    primary_discipline: str
    secondary_disciplines: list
    research_paradigm: str                # quantitative / qualitative / mixed / theoretical / review
    methodology_type: str
    target_journal_tier: str              # Q1-Q4
    reviewer_configs: list                # 5个审稿人的身份配置

    # ── Phase 1: 并行审稿 ──
    eic_report: dict
    methodology_report: dict
    domain_report: dict
    perspective_report: dict
    devils_advocate_report: dict

    # ── Phase 2: 编辑综合 ──
    editorial_decision: str               # Accept / Minor Revision / Major Revision / Reject
    consensus_analysis: dict
    dimension_scores: dict                # 5维度加权分数
    revision_roadmap: dict
```

---

## 4. 工作流设计

```
[start]
   │
   ▼
[field_analyst_node]          ← 读取论文 → 识别领域 → 生成5个审稿人配置卡
   │
   ├────────────────────────────────────────────────┐
   │           │           │           │            │
   ▼           ▼           ▼           ▼            ▼
[eic]     [methodology] [domain]  [perspective]  [devils_advocate]
   │           │           │           │            │
   │           │           │           │            │
   └───────────┴───────────┴───────────┴────────────┘
                           │
                           ▼
               [synthesizer_node]     ← 综合6份报告 → Editorial Decision + Roadmap
                           │
                          [END]
```

### LangGraph 实现要点

```python
graph = StateGraph(ReviewState)

# Phase 0
graph.add_node("field_analyst", field_analyst_node)

# Phase 1: 并行审稿人
graph.add_node("eic", eic_node)
graph.add_node("methodology", methodology_node)
graph.add_node("domain", domain_node)
graph.add_node("perspective", perspective_node)
graph.add_node("devils_advocate", devils_advocate_node)

# Phase 2: 综合
graph.add_node("synthesizer", synthesizer_node)

# 边：field_analyst → 5个并行审稿人
graph.add_edge("field_analyst", "eic")
graph.add_edge("field_analyst", "methodology")
graph.add_edge("field_analyst", "domain")
graph.add_edge("field_analyst", "perspective")
graph.add_edge("field_analyst", "devils_advocate")

# 边：5个审稿人全部完成后 → synthesizer
# (LangGraph 天然支持：所有前置节点都完成后才执行下一节点)
graph.add_edge("eic", "synthesizer")
graph.add_edge("methodology", "synthesizer")
graph.add_edge("domain", "synthesizer")
graph.add_edge("perspective", "synthesizer")
graph.add_edge("devils_advocate", "synthesizer")
```

> LangGraph 的工作方式是：当 `synthesizer` 的所有入边前置节点都执行完毕后，才会触发 `synthesizer`。5 个审稿人并行执行。

---

## 5. Prompt 设计（每个 Agent 的 System Prompt）

### 5.1 Field Analyst Agent

```
You are a senior academic publishing consultant with 20 years of cross-disciplinary
academic journal editorial experience.

Read the paper and analyze SIX dimensions:
1. Primary Discipline
2. Secondary Disciplines (max 3)
3. Research Paradigm (quantitative/qualitative/mixed/theoretical/review)
4. Methodology Type
5. Target Journal Tier (Q1-Q4)
6. Paper Maturity

Then dynamically generate specific identity cards for 5 reviewers:
- EIC: Which journal's editor, expertise area, review preferences
- R1 (Methodology): Methodological expertise, specific focus areas
- R2 (Domain): Domain expertise, research interests
- R3 (Perspective): Cross-disciplinary angle, unique viewpoint
- Devil's Advocate: Core argument challenger, void of scoring role

Output structured Reviewer Configuration Cards.
```

### 5.2 EIC Agent

```
You are the Editor-in-Chief configured by Reviewer Config Card #1.

Focus: bird's-eye view — journal fit, originality, significance, overall quality.
You do NOT dive into methodological technical details (that's R1's job).

Evaluate 5 dimensions (0-100 each) with behavioral anchors.
Output structured EIC Review Card with:
- Recommendation (Accept/Minor/Major/Reject)
- Confidence (1-5)
- 3-5 strengths (cite specific passages)
- 3-5 weaknesses (cite specific passages + fix suggestions + severity)
- Dimension scores
```

### 5.3 Methodology Reviewer Agent

```
You are a research methodology expert, Peer Reviewer 1.

Focus: rigor of research design — Can methods answer the questions? Is data
collection appropriate? Are analysis methods correct? Are conclusions supported
by data? Reproducibility?

You do NOT handle: literature completeness (R2), cross-disciplinary impact (R3).

Output structured Methodology Review Card.
```

### 5.4 Domain Reviewer Agent

```
You are a domain expert, Peer Reviewer 2.

Focus: literature coverage, theoretical framework appropriateness, domain
contribution, missing key references. Also report on Literature Integration
(optional dimension).

Output structured Domain Review Card.
```

### 5.5 Perspective Reviewer Agent

```
You are a cross-disciplinary reviewer, Peer Reviewer 3.

Focus: cross-disciplinary connections, practical applications and policy
implications, broader social/ethical implications, challenging fundamental
assumptions. Also report on Significance & Impact (optional dimension).

Output structured Perspective Review Card.
```

### 5.6 Devil's Advocate Agent

```
You are the Devil's Advocate. Your job is NOT to score, but to find the most
vulnerable points, biggest logical gaps, and strongest counter-arguments.
You are the "stress test" before submission.

8 Challenge Dimensions:
1. Core Thesis Challenge
2. Cherry-Picking Detection
3. Confirmation Bias Detection
4. Logic Chain Validation
5. Overgeneralization Check
6. Alternative Paths Analysis
7. Stakeholder Blind Spots
8. "So What?" Test

Output: Strongest Counter-Argument + Issue List (CRITICAL/MAJOR/MINOR) +
Ignored Alternatives + Missing Stakeholders.

IRON RULE: You do NOT score the paper. You challenge, not score.
If DA finds CRITICAL → Editorial Decision cannot be Accept.
```

### 5.7 Editorial Synthesizer Agent

```
You are the Managing Editor. You are NOT a 6th reviewer.
Your job: synthesize and arbitrate, NOT raise new review comments.

Steps:
1. Report Inventory: organize 5 reports into structured table
2. Consensus Identification (CONSENSUS-4, CONSENSUS-3, SPLIT)
3. Disagreement Resolution (evidence-first, expertise-first)
4. Decision Making (Accept/Minor/Major/Reject per rubric)
5. Revision Roadmap (Priority 1-3 checklist)

DA-CRITICAL issues MUST appear in final Decision.
Synthesizer CANNOT fabricate comments — must trace to specific reviewer reports.
```

---

## 6. 评分 Rubric 设计

每个维度 0-100，按行为锚定分 5 档：

### 原创性 (20%)

| 分数段 | 描述符 | 行为指标 |
|--------|--------|---------|
| 90-100 | 卓越 | 全新理论框架+实证支持；开辟全新研究方向；影响3+领域 |
| 75-89 | 强 | 新方法或将现有理论应用于新情境；明确的增量外贡献 |
| 60-74 | 合格 | 用新数据/人群/情境扩展现有框架；贡献清晰但增量性 |
| 45-59 | 弱 | 重复现有研究但变异微小；"so what?"问题未回答 |
| <45 | 不足 | 无原创贡献；无正当理由重复已有工作 |

### 方法严谨性 (25%)

| 分数段 | 描述符 | 行为指标 |
|--------|--------|---------|
| 90-100 | 卓越 | 研究设计完美对齐RQ；所有效度威胁已处理；可重复 |
| 75-89 | 强 | 健全设计+微小缺口；适当方法+微小报告遗漏 |
| 60-74 | 合格 | 可接受设计但有些效度问题；方法适当但论证不足 |
| 45-59 | 弱 | 设计有重大缺陷；方法选择存疑 |
| <45 | 不足 | 基础设计缺陷使发现无效 |

### 证据充分性 (25%)

| 分数段 | 描述符 | 行为指标 |
|--------|--------|---------|
| 90-100 | 卓越 | >40来源，80%+同行评审，多方法三角验证 |
| 75-89 | 强 | 25-40来源，70%+同行评审，主要主张有充分证据 |
| 60-74 | 合格 | 15-25来源，60%+同行评审，关键主张有支持但有限 |
| 45-59 | 弱 | <15来源或<50%同行评审，多个无支持主张 |
| <45 | 不足 | 严重来源不足，主要主张无支持 |

### 论证连贯性 (15%)

| 分数段 | 描述符 | 行为指标 |
|--------|--------|---------|
| 90-100 | 卓越 | 从问题→缺口→RQ→方法→发现→影响的清晰逻辑流 |
| 75-89 | 强 | 清晰逻辑流+微小缺口；论证总体有说服力 |
| 60-74 | 合格 | 主要论证可见但有些断开；结论基本跟随证据 |
| 45-59 | 弱 | 论证结构不清；结论超越证据 |
| <45 | 不足 | 无连贯论证；结论不跟随证据 |

### 写作质量 (15%)

| 分数段 | 描述符 | 行为指标 |
|--------|--------|---------|
| 90-100 | 卓越 | 专业学术散文；精确术语；零语法错误 |
| 75-89 | 强 | 良好学术写作；少量风格不一致 |
| 60-74 | 合格 | 可接受但有些啰嗦；术语欠精确 |
| 45-59 | 弱 | 低于期刊标准；频繁不清晰段落 |
| <45 | 不足 | 不可接受的写作质量；无法理解段落 |

### 分数→决定映射

| 加权平均分 | 决定 |
|-----------|------|
| ≥80 | Accept |
| 65-79 | Minor Revision |
| 50-64 | Major Revision |
| <50 | Reject |

---

## 7. 输出格式

### 审稿人报告（统一结构）

```json
{
  "reviewer_role": "EIC / Methodology / Domain / Perspective",
  "recommendation": "Accept / Minor Revision / Major Revision / Reject",
  "confidence": 3,
  "dimension_scores": {
    "originality": 78,
    "methodology": 65,
    "evidence": 72,
    "coherence": 80,
    "writing": 75
  },
  "weighted_average": 73.2,
  "strengths": [
    {"title": "...", "description": "...", "citation": "p. X"}
  ],
  "weaknesses": [
    {"title": "...", "problem": "...", "why_it_matters": "...", "suggestion": "...", "severity": "Major"}
  ],
  "questions_for_author": ["...", "..."]
}
```

### Devil's Advocate 报告

```json
{
  "strongest_counter_argument": "...",
  "issues": {
    "CRITICAL": [{"dimension": "...", "description": "...", "location": "p. X"}],
    "MAJOR": [...],
    "MINOR": [...]
  },
  "ignored_alternatives": ["..."],
  "missing_stakeholders": ["..."],
  "unexamined_premise": "..."
}
```

### 编辑综合报告

```json
{
  "editorial_decision": "Major Revision",
  "decision_rationale": "...",
  "consensus": {
    "consensus_4": ["..."],
    "consensus_3": ["..."],
    "splits": [{"issue": "...", "positions": "...", "resolution": "..."}]
  },
  "devils_advocate_critical_handling": "...",
  "revision_roadmap": {
    "priority_1_structural": [
      {"item": "...", "source": "R1", "effort": "3 days"}
    ],
    "priority_2_content": [...],
    "priority_3_formatting": [...]
  },
  "final_scores": {
    "originality": 78,
    "methodology": 65,
    "evidence": 72,
    "coherence": 80,
    "writing": 75,
    "weighted_total": 73.2
  }
}
```

---

## 8. 项目结构（预期）

```
Agent-AI/
├── Reviewer.py                    ← 旧版（保留/迁移）
├── paper_reviewer/                ← 新版多角色审稿系统
│   ├── __init__.py
│   ├── main.py                    # 入口 + CLI
│   ├── graph.py                   # LangGraph 图构建
│   ├── state.py                   # ReviewState 定义
│   ├── rubrics.py                 # 评分 rubric 数据
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── field_analyst.py      # Phase 0: 领域分析
│   │   ├── eic.py                 # EIC 审稿人
│   │   ├── methodology_reviewer.py # R1 方法论
│   │   ├── domain_reviewer.py     # R2 领域专家
│   │   ├── perspective_reviewer.py # R3 跨学科
│   │   ├── devils_advocate.py    # 魔鬼代言人
│   │   └── synthesizer.py         # 编辑综合
│   ├── prompts/
│   │   ├── __init__.py
│   │   ├── system_prompts.py     # 所有 agent 的 system prompt
│   │   └── output_schemas.py     # 输出格式定义
│   └── utils.py                   # 分数计算、语言检测等
├── docs/superpowers/specs/
│   └── 2026-07-11-paper-reviewer-design.md  ← 本文件
└── tests/
    └── test_paper_reviewer.py
```

---

## 9. 与现有 Reviewer.py 的关系

| 现有组件 | 改造方式 |
|---------|---------|
| `State` (TypedDict) | 替换为新 `ReviewState`，旧 `State` 不删除（向后兼容） |
| `extract_score()` | 升级为结构化 score extraction（从 JSON 中提取各维度分数） |
| `check_relevance()` 等 4 函数 | 升级为独立 Agent 节点 |
| `build_workflow()` | 扩展为 7 节点图（1 analyst + 5 reviewers + 1 synthesizer） |
| `grade_essay()` | 重命名为 `review_paper()`，接口兼容 |
| `read_text_from_file()` | 保留，新增语言检测 |
| MiMo API 配置 | 保留，可切换 |

---

## 10. 关键约束与原则

1. **5 审稿人独立评审**：每个 agent 只看到自己的配置卡，不看其他审稿人报告
2. **Synthesizer 不捏造**：所有综合意见必须有 Phase 1 报告可追溯
3. **DA CRITICAL → 不接受**：如果魔鬼代言人发现问题为 CRITICAL，编辑决定不能是 Accept
4. **READ-ONLY**：审稿 agent 不得修改论文原文
5. **引用原文**：所有优缺点必须引用论文具体段落
6. **默认中文输出**：无论论文语言，审稿报告默认使用中文；学术术语保留英文原文
7. **Placeholder 禁止**：报告中不得出现 TBD、"appropriate handling" 等占位符

---

## 11. 技术依赖

```
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-core>=0.3.0
pydantic>=2.0          # 结构化输出验证
python-dotenv>=1.0
PyPDF2>=3.0            # PDF 读取（已有）
```

---

## 12. 验收标准

- [ ] 能读入一篇论文并自动识别领域
- [ ] 生成 5 个具体审稿人身份（非模板化）
- [ ] 5 份独立审稿报告各自从不同角度
- [ ] 每份报告包含：推荐决定、置信度、5 维度分数、优缺点（带引用）
- [ ] Devil's Advocate 产出最强反证 + 问题清单
- [ ] Synthesizer 产出编辑决定 + 修订路线图
- [ ] DA CRITICAL → 编辑决定 ≠ Accept
- [ ] 中文论文 → 中文评审；英文论文 → 英文评审
