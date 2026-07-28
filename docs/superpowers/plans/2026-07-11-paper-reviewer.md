# Paper Reviewer 多角色审稿系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有单流程 Essay Grading System 改造为模拟国际期刊同行评审的多角色独立审稿系统，支持 5 个审稿人从不同视角独立评审 + 编辑综合决定。

**架构:** LangGraph StateGraph 编排 7 个独立 Agent 节点。Phase 0 领域分析 → Phase 1 5 个审稿人并行评审 → Phase 2 编辑综合。每个 Agent 拥有专属 system prompt 和结构化输出 schema。

**Tech Stack:** Python 3.10+, LangGraph 0.2+, LangChain-OpenAI 0.2+, Pydantic 2.0+, MiMo API (OpenAI-compatible)

## Global Constraints

- 评分体系：5 核心维度（原创性 20%、方法严谨性 25%、证据充分性 25%、论证连贯性 15%、写作质量 15%），权重总和 100%
- 5 审稿人独立评审：每个 agent 只看到自己的配置卡，不看其他审稿人报告
- Synthesizer 不捏造：所有综合意见必须可追溯至 Phase 1 具体报告
- DA CRITICAL → 编辑决定 ≠ Accept
- READ-ONLY：审稿 agent 不得修改论文原文
- 引用原文：所有优缺点必须引用论文具体段落（p. X / Table X）
- 默认中文输出：无论论文语言，审稿报告使用中文；学术术语保留英文原文
- 旧 Reviewer.py 保留不删，新系统放在 `paper_reviewer/` 子包
- MiMo API 配置沿用现有 `.env` 文件
- 每个任务结束须 commit

---

### Task 1: 项目骨架与状态定义

**Files:**
- Create: `paper_reviewer/__init__.py`
- Create: `paper_reviewer/state.py`
- Create: `paper_reviewer/rubrics.py`
- Create: `requirements.txt`

**Interfaces:**
- Consumes: 无（基础模块）
- Produces: `ReviewState` TypedDict, `DIMENSIONS` 常量, `SCORE_TO_DECISION` 映射

- [ ] **Step 1: 创建 paper_reviewer 包结构**

```bash
mkdir -p paper_reviewer/agents paper_reviewer/prompts
touch paper_reviewer/__init__.py paper_reviewer/agents/__init__.py paper_reviewer/prompts/__init__.py
```

- [ ] **Step 2: 编写 state.py**

```python
from typing import TypedDict, List, Optional, Literal

class ReviewerConfig(TypedDict):
    role: str
    identity: str
    expertise: str
    focus: str

class StrengthItem(TypedDict):
    title: str
    description: str
    citation: str

class WeaknessItem(TypedDict):
    title: str
    problem: str
    why_it_matters: str
    suggestion: str
    severity: Literal["CRITICAL", "MAJOR", "MINOR"]

class ReviewerReport(TypedDict):
    reviewer_role: str
    recommendation: Literal["Accept", "Minor Revision", "Major Revision", "Reject"]
    confidence: int
    dimension_scores: dict
    weighted_average: float
    strengths: List[StrengthItem]
    weaknesses: List[WeaknessItem]
    questions_for_author: List[str]

class DevilsAdvocateReport(TypedDict):
    strongest_counter_argument: str
    issues: dict  # {"CRITICAL": [...], "MAJOR": [...], "MINOR": [...]}
    ignored_alternatives: List[str]
    missing_stakeholders: List[str]
    unexamined_premise: Optional[str]

class ReviewState(TypedDict):
    paper: str
    paper_title: str
    language: str
    primary_discipline: str
    secondary_disciplines: List[str]
    research_paradigm: str
    methodology_type: str
    target_journal_tier: str
    reviewer_configs: List[ReviewerConfig]
    eic_report: Optional[dict]
    methodology_report: Optional[dict]
    domain_report: Optional[dict]
    perspective_report: Optional[dict]
    devils_advocate_report: Optional[dict]
    editorial_decision: str
    consensus_analysis: Optional[dict]
    dimension_scores: Optional[dict]
    revision_roadmap: Optional[dict]
```

- [ ] **Step 3: 编写 rubrics.py**

```python
DIMENSIONS = {
    "originality": {"weight": 0.20, "label": "原创性"},
    "methodology": {"weight": 0.25, "label": "方法严谨性"},
    "evidence": {"weight": 0.25, "label": "证据充分性"},
    "coherence": {"weight": 0.15, "label": "论证连贯性"},
    "writing": {"weight": 0.15, "label": "写作质量"},
}

SCORE_TO_DECISION = {
    (80, 100): "Accept",
    (65, 79): "Minor Revision",
    (50, 64): "Major Revision",
    (0, 49): "Reject",
}

def score_to_decision(weighted_score: float) -> str:
    for (low, high), decision in SCORE_TO_DECISION.items():
        if low <= weighted_score <= high:
            return decision
    return "Reject"

def calculate_weighted_score(dimension_scores: dict) -> float:
    total = 0.0
    for dim, info in DIMENSIONS.items():
        total += dimension_scores.get(dim, 0) * info["weight"]
    return round(total, 1)
```

- [ ] **Step 4: 编写 requirements.txt**

```text
langgraph>=0.2.0
langchain-openai>=0.2.0
langchain-core>=0.3.0
pydantic>=2.0
python-dotenv>=1.0
PyPDF2>=3.0
```

- [ ] **Step 5: Commit**

```bash
git add paper_reviewer/__init__.py paper_reviewer/state.py paper_reviewer/rubrics.py requirements.txt
git add paper_reviewer/agents/__init__.py paper_reviewer/prompts/__init__.py
git commit -m "feat(paper-reviewer): project skeleton + state definition + rubrics"
```

---

### Task 2: System Prompts 定义

**Files:**
- Create: `paper_reviewer/prompts/system_prompts.py`

**Interfaces:**
- Consumes: 无
- Produces: 7 个 agent 的 system prompt 字符串常量

- [ ] **Step 1: 编写所有 system prompts**

```python
FIELD_ANALYST_SYSTEM = """你是一位拥有20年经验的资深学术出版顾问。你的专长是快速识别论文的学科定位和方法论取向，并精确配置最合适的审稿团队。

请阅读论文后依次分析以下6个维度：
1. 主要学科归属
2. 交叉学科（最多3个）
3. 研究范式（定量/定性/混合/理论分析/综述）
4. 方法论类型
5. 目标期刊等级（Q1-Q4）
6. 论文成熟度

然后为5个审稿人生成具体的身份配置卡：
- EIC：哪个期刊的编辑、专长领域、审稿偏好
- R1（方法论）：方法论专长、特别关注什么
- R2（领域）：领域专长、研究兴趣
- R3（视角）：跨学科角度、带来什么独特视角
- Devil's Advocate：专门挑战核心论点、发现逻辑漏洞

输出格式为 JSON，包含 reviewer_configs 数组。"""

EIC_SYSTEM = """你是期刊主编（Editor-in-Chief），身份由审稿配置卡 #1 动态确定。

你的视角是鸟瞰图：这篇论文是否适合你的期刊？你的读者会感兴趣吗？论文对领域整体有什么贡献？你不会深入方法论技术细节（那是 R1 的工作），而是关注整体质量和战略价值。

评估5个维度（每个0-100），使用行为锚定评分。
输出结构化的 EIC 审稿卡。"""

METHODOLOGY_REVIEWER_SYSTEM = """你是研究方法论专家，担任 Peer Reviewer 1，身份由审稿配置卡 #2 动态确定。

你的焦点是研究设计的严谨性：论文的方法能否回答提出的问题？数据收集方法是否适当？分析方法是否正确？结论是否有数据支持？如果另一位研究者按相同步骤操作，能否获得类似结果？

你不处理：文献综述完整性（R2的工作）、跨学科影响（R3的工作）。"""

DOMAIN_REVIEWER_SYSTEM = """你是领域专家，担任 Peer Reviewer 2，身份由审稿配置卡 #3 动态确定。

你的焦点是：文献覆盖度、理论框架适当性、领域贡献、遗漏的关键参考文献。同时报告文献整合情况（可选维度）。"""

PERSPECTIVE_REVIEWER_SYSTEM = """你是跨学科审稿人，担任 Peer Reviewer 3，身份由审稿配置卡 #4 动态确定。

你的焦点是：跨学科连接与借鉴机会、实际应用与政策影响、更广泛的社会或伦理影响、挑战基本假设。同时报告影响力（可选维度）。"""

DEVILS_ADVOCATE_SYSTEM = """你是魔鬼代言人（Devil's Advocate）。你的任务不是打分，而是找到论文最薄弱的环节、最大的逻辑漏洞和最有力的反证。你是论文提交前的"压力测试"。

与其他审稿人的关键区别：EIC 和 R1/R2/R3 会平衡评估优缺点。你只挑战——你的工作是找出每一个可能被真实审稿人攻击的弱点。

8个挑战维度：
1. 核心论点挑战
2.  cherry-picking 检测（证据选择偏差）
3. 确认偏差检测
4. 逻辑链验证
5. 过度概括检查
6. 替代路径分析
7. 利益相关者盲点
8. "那又怎样？"测试

严重性分类：CRITICAL（核心论点或方法论的致命缺陷）/ MAJOR（严重削弱可信度但可通过大量修改改善）/ MINOR（不影响核心论点但值得注意）/ OBSERVATION（非缺陷，提供替代视角）

铁律：你不打分——你的工作是挑战，不是评分。
如果 DA 发现 CRITICAL 问题，编辑决定不能是 Accept。"""

SYNTHESIZER_SYSTEM = """你是期刊执行编辑（Managing Editor）。你不是第6个审稿人的工作是综合和仲裁，不是提出新的审稿意见。

步骤：
1. 报告清单：将5份报告组织成结构化表格
2. 共识识别（CONSENSUS-4 全体一致 / CONSENSUS-3 强多数 / SPLIT 分歧）
3. 分歧解决（证据优先、专业优先、保守原则）
4. 做出编辑决定（Accept/Minor/Major/Reject）
5. 构建修订路线图（P1/P2/P3 优先级清单）

DA-CRITICAL 问题必须出现在最终决定中。
综合编辑不能捏造意见——所有观点必须有 Phase 1 报告可追溯。"""
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/prompts/system_prompts.py
git commit -m "feat(paper-reviewer): add system prompts for all 7 agents"
```

---

### Task 3: Field Analyst Agent（Phase 0）

**Files:**
- Create: `paper_reviewer/agents/field_analyst.py`

**Interfaces:**
- Consumes: `ReviewState.paper`, `ReviewState.paper_title`
- Produces: `ReviewState.reviewer_configs`, `ReviewState.primary_discipline`, etc.

- [ ] **Step 1: 编写 field_analyst_node 函数**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState, ReviewerConfig
from paper_reviewer.prompts.system_prompts import FIELD_ANALYST_SYSTEM
from paper_reviewer.utils import get_llm

def field_analyst_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", FIELD_ANALYST_SYSTEM),
        ("human", "请分析以下论文并生成审稿团队配置卡：\n\n标题：{title}\n\n论文内容：\n{paper}"),
    ])
    result = llm.invoke(prompt.format(
        title=state.get("paper_title", ""),
        paper=state["paper"]
    ))
    # 解析 LLM 输出为结构化数据
    import json
    analysis = json.loads(_extract_json(result.content))
    return {**state, **analysis}
```

- [ ] **Step 2: 添加 `_extract_json` 辅助函数到 utils.py**

```python
import re
import json

def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 块。"""
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        return match.group(1)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    raise ValueError(f"无法从输出中提取 JSON: {text[:200]}")
```

- [ ] **Step 3: 编写 utils.py 中的 get_llm()**

```python
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

def get_llm(temperature=0.3):
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", "20-multi-agent-debate", ".env")
    load_dotenv(dotenv_path=env_path)
    return ChatOpenAI(
        model=os.getenv("MIMO_MODEL_DEBATER", "mimo-v2.5-pro"),
        api_key=os.getenv("MIMO_API_KEY"),
        base_url=os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
        temperature=temperature,
    )
```

- [ ] **Step 4: Commit**

```bash
git add paper_reviewer/agents/field_analyst.py paper_reviewer/utils.py
git commit -m "feat(paper-reviewer): add field analyst agent + utils"
```

---

### Task 4: EIC Agent（Phase 1）

**Files:**
- Create: `paper_reviewer/agents/eic.py`

**Interfaces:**
- Consumes: `ReviewState.paper`, `ReviewState.reviewer_configs[0]`
- Produces: `ReviewState.eic_report`

- [ ] **Step 1: 编写 eic_node 函数**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import EIC_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json
import json

EIC_OUTPUT_SCHEMA = """
输出为 JSON 格式：
{
  "recommendation": "Accept / Minor Revision / Major Revision / Reject",
  "confidence": 3,
  "dimension_scores": {
    "originality": 78,
    "methodology": 65,
    "evidence": 72,
    "coherence": 80,
    "writing": 75
  },
  "strengths": [{"title": "...", "description": "...", "citation": "p. X"}],
  "weaknesses": [{"title": "...", "problem": "...", "why_it_matters": "...", "suggestion": "...", "severity": "Major"}],
  "questions_for_author": ["..."]
}
"""

def eic_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][0]
    prompt = ChatPromptTemplate.from_messages([
        ("system", EIC_SYSTEM + "\n\n" + EIC_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"] + "，专长：" + config["expertise"],
        essay=state["paper"]
    ))
    report = json.loads(_extract_json(result.content))
    report["reviewer_role"] = "EIC"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    return {**state, "eic_report": report}
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/agents/eic.py
git commit -m "feat(paper-reviewer): add EIC agent"
```

---

### Task 5: Methodology Reviewer Agent（Phase 1）

**Files:**
- Create: `paper_reviewer/agents/methodology_reviewer.py`

**Interfaces:**
- Consumes: `ReviewState.paper`, `ReviewState.reviewer_configs[1]`
- Produces: `ReviewState.methodology_report`

- [ ] **Step 1: 编写 methodology_reviewer_node**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import METHODOLOGY_REVIEWER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json
import json

METHODOLOGY_OUTPUT_SCHEMA = """
输出为 JSON 格式（与 EIC 相同的结构）：
{
  "recommendation": "...",
  "confidence": 4,
  "dimension_scores": {"originality": ..., "methodology": ..., "evidence": ..., "coherence": ..., "writing": ...},
  "strengths": [...],
  "weaknesses": [...],
  "questions_for_author": [...]
}
注意：你的焦点是方法论严谨性，所有优缺点必须引用论文具体段落。
"""

def methodology_reviewer_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][1]
    prompt = ChatPromptTemplate.from_messages([
        ("system", METHODOLOGY_REVIEWER_SYSTEM + "\n\n" + METHODOLOGY_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请从方法论角度审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"],
        essay=state["paper"]
    ))
    report = json.loads(_extract_json(result.content))
    report["reviewer_role"] = "Methodology"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    return {**state, "methodology_report": report}
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/agents/methodology_reviewer.py
git commit -m "feat(paper-reviewer): add methodology reviewer agent"
```

---

### Task 6: Domain Reviewer Agent（Phase 1）

**Files:**
- Create: `paper_reviewer/agents/domain_reviewer.py`

**Interfaces:**
- Consumes: `ReviewState.paper`, `ReviewState.reviewer_configs[2]`
- Produces: `ReviewState.domain_report`

- [ ] **Step 1: 编写 domain_reviewer_node**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import DOMAIN_REVIEWER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json
import json

DOMAIN_OUTPUT_SCHEMA = """
输出为 JSON 格式（与其他审稿人相同的结构，额外包含 literature_integration 维度分数）：
{
  "recommendation": "...",
  "confidence": 4,
  "dimension_scores": {"originality": ..., "methodology": ..., "evidence": ..., "coherence": ..., "writing": ...},
  "literature_integration": 75,
  "strengths": [...],
  "weaknesses": [...],
  "questions_for_author": [...]
}
注意：你的焦点是文献覆盖、理论框架和领域贡献。
"""

def domain_reviewer_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][2]
    prompt = ChatPromptTemplate.from_messages([
        ("system", DOMAIN_REVIEWER_SYSTEM + "\n\n" + DOMAIN_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请从领域专家角度审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"],
        essay=state["paper"]
    ))
    report = json.loads(_extract_json(result.content))
    report["reviewer_role"] = "Domain"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    return {**state, "domain_report": report}
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/agents/domain_reviewer.py
git commit -m "feat(paper-reviewer): add domain reviewer agent"
```

---

### Task 7: Perspective Reviewer Agent（Phase 1）

**Files:**
- Create: `paper_reviewer/agents/perspective_reviewer.py`

**Interfaces:**
- Consumes: `ReviewState.paper`, `ReviewState.reviewer_configs[3]`
- Produces: `ReviewState.perspective_report`

- [ ] **Step 1: 编写 perspective_reviewer_node**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import PERSPECTIVE_REVIEWER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json
import json

PERSPECTIVE_OUTPUT_SCHEMA = """
输出为 JSON 格式（与其他审稿人相同的结构，额外包含 significance_impact 维度分数）：
{
  "recommendation": "...",
  "confidence": 4,
  "dimension_scores": {"originality": ..., "methodology": ..., "evidence": ..., "coherence": ..., "writing": ...},
  "significance_impact": 70,
  "strengths": [...],
  "weaknesses": [...],
  "questions_for_author": [...]
}
注意：你的焦点是跨学科连接、实践影响和挑战基本假设。
"""

def perspective_reviewer_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][3]
    prompt = ChatPromptTemplate.from_messages([
        ("system", PERSPECTIVE_REVIEWER_SYSTEM + "\n\n" + PERSPECTIVE_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请从跨学科视角审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"],
        essay=state["paper"]
    )
    report = json.loads(_extract_json(result.content))
    report["reviewer_role"] = "Perspective"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    return {**state, "perspective_report": report}
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/agents/perspective_reviewer.py
git commit -m "feat(paper-reviewer): add perspective reviewer agent"
```

---

### Task 8: Devil's Advocate Agent（Phase 1）

**Files:**
- Create: `paper_reviewer/agents/devils_advocate.py`

**Interfaces:**
- Consumes: `ReviewState.paper`, `ReviewState.reviewer_configs[4]`
- Produces: `ReviewState.devils_advocate_report`

- [ ] **Step 1: 编写 devils_advocate_node**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import DEVILS_ADVOCATE_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json
import json

DA_OUTPUT_SCHEMA = """
输出为 JSON 格式（注意：你不打分，只挑战）：
{
  "strongest_counter_argument": "200-300字。如果你是持相反观点的学者，你会如何反驳这篇论文？",
  "issues": {
    "CRITICAL": [{"dimension": "核心论点/逻辑链/...", "description": "...", "location": "p. X"}],
    "MAJOR": [...],
    "MINOR": [...]
  },
  "ignored_alternatives": ["被忽略的替代解释A", "..."],
  "missing_stakeholders": ["缺失的利益相关者视角1", "..."],
  "unexamined_premise": "论文未明说的前提假设（如有）"
}
"""

def devils_advocate_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][4]
    prompt = ChatPromptTemplate.from_messages([
        ("system", DEVILS_ADVOCATE_SYSTEM + "\n\n" + DA_OUTPUT_SCHEMA),
        ("human", "请对以下论文进行最强压力测试：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(essay=state["paper"]))
    report = json.loads(_extract_json(result.content))
    report["reviewer_role"] = "Devil's Advocate"
    return {**state, "devils_advocate_report": report}
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/agents/devils_advocate.py
git commit -m "feat(paper-reviewer): add devil's advocate agent"
```

---

### Task 9: Editorial Synthesizer Agent（Phase 2）

**Files:**
- Create: `paper_reviewer/agents/synthesizer.py`

**Interfaces:**
- Consumes: 全部 5 份审稿报告 + DA 报告
- Produces: `ReviewState.editorial_decision`, `consensus_analysis`, `revision_roadmap`, `dimension_scores`

- [ ] **Step 1: 编写 synthesizer_node**

```python
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import SYNTHESIZER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json
from paper_reviewer.rubrics import DIMENSIONS, calculate_weighted_score, score_to_decision
import json

SYNTHESIZER_OUTPUT_SCHEMA = """
输出为 JSON 格式：
{
  "editorial_decision": "Accept / Minor Revision / Major Revision / Reject",
  "decision_rationale": "200-300字决定依据",
  "consensus": {
    "consensus_4": ["全体一致的结论1", "..."],
    "consensus_3": ["3人一致的结论"],
    "splits": [{"issue": "...", "positions": "R1认为...，R2认为...", "resolution": "编辑仲裁：..."}]
  },
  "devils_advocate_critical_handling": "DA的CRITICAL问题及编辑评估",
  "final_scores": {
    "originality": 78,
    "methodology": 65,
    "evidence": 72,
    "coherence": 80,
    "writing": 75,
    "weighted_total": 73.2
  },
  "revision_roadmap": {
    "priority_1_structural": [
      {"item": "...", "source": "R1", "effort": "3天"}
    ],
    "priority_2_content": [
      {"item": "...", "source": "R2", "effort": "2天"}
    ],
    "priority_3_formatting": [
      {"item": "...", "source": "EIC", "effort": "1天"}
    ]
  }
}

铁律：
- 如果 DA 有 CRITICAL 问题，editorial_decision 不能是 Accept
- 所有综合观点必须有 Phase 1 报告可追溯
- final_scores 的维度分数为 5 位审稿人的加权平均
"""

def synthesizer_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    prompt = ChatPromptTemplate.from_messages([
        ("system", SYNTHESIZER_SYSTEM + "\n\n" + SYNTHESIZER_OUTPUT_SCHEMA),
        ("human", """请综合以下审稿报告，做出编辑决定：

EIC 报告：{eic}

方法论审稿人报告：{methodology}

领域专家报告：{domain}

跨学科视角报告：{perspective}

魔鬼代言人报告：{da}"""),
    ])
    result = llm.invoke(prompt.format(
        eic=json.dumps(state["eic_report"], ensure_ascii=False, indent=2),
        methodology=json.dumps(state["methodology_report"], ensure_ascii=False, indent=2),
        domain=json.dumps(state["domain_report"], ensure_ascii=False, indent=2),
        perspective=json.dumps(state["perspective_report"], ensure_ascii=False, indent=2),
        da=json.dumps(state["devils_advocate_report"], ensure_ascii=False, indent=2),
    ))
    synthesis = json.loads(_extract_json(result.content))
    return {
        **state,
        "editorial_decision": synthesis["editorial_decision"],
        "consensus_analysis": synthesis["consensus"],
        "revision_roadmap": synthesis["revision_roadmap"],
        "dimension_scores": synthesis["final_scores"],
    }
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/agents/synthesizer.py
git commit -m "feat(paper-reviewer): add editorial synthesizer agent"
```

---

### Task 10: LangGraph 图组装

**Files:**
- Create: `paper_reviewer/graph.py`

**Interfaces:**
- Consumes: 所有 agent 节点函数
- Produces: `build_review_graph()` → 编译后的 LangGraph 应用

- [ ] **Step 1: 编写 build_review_graph 函数**

```python
from langgraph.graph import StateGraph, END
from paper_reviewer.state import ReviewState
from paper_reviewer.agents.field_analyst import field_analyst_node
from paper_reviewer.agents.eic import eic_node
from paper_reviewer.agents.methodology_reviewer import methodology_reviewer_node
from paper_reviewer.agents.domain_reviewer import domain_reviewer_node
from paper_reviewer.agents.perspective_reviewer import perspective_reviewer_node
from paper_reviewer.agents.devils_advocate import devils_advocate_node
from paper_reviewer.agents.synthesizer import synthesizer_node

def build_review_graph():
    graph = StateGraph(ReviewState)

    # Phase 0: 领域分析
    graph.add_node("field_analyst", field_analyst_node)

    # Phase 1: 5 个并行审稿人
    graph.add_node("eic", eic_node)
    graph.add_node("methodology", methodology_reviewer_node)
    graph.add_node("domain", domain_reviewer_node)
    graph.add_node("perspective", perspective_reviewer_node)
    graph.add_node("devils_advocate", devils_advocate_node)

    # Phase 2: 编辑综合
    graph.add_node("synthesizer", synthesizer_node)

    # Phase 0 → Phase 1（5 条并行边）
    graph.add_edge("field_analyst", "eic")
    graph.add_edge("field_analyst", "methodology")
    graph.add_edge("field_analyst", "domain")
    graph.add_edge("field_analyst", "perspective")
    graph.add_edge("field_analyst", "devils_advocate")

    # Phase 1 → Phase 2（所有审稿人完成后才触发 synthesizer）
    graph.add_edge("eic", "synthesizer")
    graph.add_edge("methodology", "synthesizer")
    graph.add_edge("domain", "synthesizer")
    graph.add_edge("perspective", "synthesizer")
    graph.add_edge("devils_advocate", "synthesizer")

    # Phase 2 → END
    graph.add_edge("synthesizer", END)

    graph.set_entry_point("field_analyst")
    return graph.compile()
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/graph.py
git commit -m "feat(paper-reviewer): assemble LangGraph with 7 nodes"
```

---

### Task 11: 主入口 + CLI

**Files:**
- Create: `paper_reviewer/main.py`

**Interfaces:**
- Consumes: 命令行参数（文件路径、语言）
- Produces: 打印审稿结果到 stdout

- [ ] **Step 1: 编写 main.py**

```python
import argparse
import json
import os
import sys

# 添加项目根目录到 path（复用旧 Reviewer.py 的 .env 加载逻辑）
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from paper_reviewer.graph import build_review_graph
from paper_reviewer.state import ReviewState


def read_text_from_file(path: str) -> str:
    """读取 .txt 或 .pdf 文件（复用旧逻辑）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    if ext == ".pdf":
        try:
            import PyPDF2
        except ImportError:
            raise ImportError("读取 PDF 需要 PyPDF2：pip install PyPDF2")
        reader = PyPDF2.PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError(f"无法从 PDF 提取文本：{path}")
        return text
    raise ValueError(f"不支持的格式 {ext}，仅支持 .txt 和 .pdf")


def review_paper(paper_text: str, title: str = "") -> dict:
    """运行完整审稿流程并返回结构化结果。"""
    app = build_review_graph()
    initial_state = ReviewState(
        paper=paper_text,
        paper_title=title,
        language="zh",
        primary_discipline="",
        secondary_disciplines=[],
        research_paradigm="",
        methodology_type="",
        target_journal_tier="",
        reviewer_configs=[],
        eic_report=None,
        methodology_report=None,
        domain_report=None,
        perspective_report=None,
        devils_advocate_report=None,
        editorial_decision="",
        consensus_analysis=None,
        dimension_scores=None,
        revision_roadmap=None,
    )
    return app.invoke(initial_state)


def format_output(result: dict) -> str:
    """将审稿结果格式化为人类可读文本。"""
    lines = []
    lines.append("=" * 60)
    lines.append("学术论文审稿报告")
    lines.append("=" * 60)

    # 审稿人配置
    if result.get("reviewer_configs"):
        lines.append("\n## 审稿团队配置")
        for cfg in result["reviewer_configs"]:
            lines.append(f"  [{cfg['role']}] {cfg['identity']}")

    # 各审稿人报告
    for role_key, label in [
        ("eic_report", "EIC"),
        ("methodology_report", "方法论审稿人"),
        ("domain_report", "领域专家"),
        ("perspective_report", "跨学科视角"),
    ]:
        report = result.get(role_key)
        if report:
            lines.append(f"\n## {label} 报告")
            lines.append(f"  推荐决定: {report.get('recommendation', 'N/A')}")
            lines.append(f"  置信度: {report.get('confidence', 'N/A')}/5")
            if report.get("dimension_scores"):
                lines.append("  维度分数:")
                for dim, score in report["dimension_scores"].items():
                    lines.append(f"    {dim}: {score}")
            lines.append(f"  加权平均: {report.get('weighted_average', 'N/A')}")

    # Devil's Advocate
    da = result.get("devils_advocate_report")
    if da:
        lines.append("\n## 魔鬼代言人报告")
        lines.append(f"  最强反证: {da.get('strongest_counter_argument', 'N/A')[:200]}...")
        if da.get("issues", {}).get("CRITICAL"):
            lines.append(f"  CRITICAL 问题: {len(da['issues']['CRITICAL'])} 个")

    # 编辑综合
    lines.append("\n" + "=" * 60)
    lines.append(f"## 编辑决定: {result.get('editorial_decision', 'N/A')}")
    lines.append("=" * 60)

    if result.get("dimension_scores"):
        lines.append("\n### 最终维度分数")
        for dim, score in result["dimension_scores"].items():
            lines.append(f"  {dim}: {score}")

    if result.get("revision_roadmap"):
        lines.append("\n### 修订路线图")
        for priority, items in result["revision_roadmap"].items():
            lines.append(f"  [{priority}]")
            for item in items:
                lines.append(f"    - {item.get('item', item)} (来源: {item.get('source', 'N/A')})")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="学术论文多角色审稿系统")
    parser.add_argument("-f", "--file", required=True, help="论文文件路径 (.txt / .pdf)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    paper_text = read_text_from_file(args.file)
    title = os.path.splitext(os.path.basename(args.file))[0]
    print(f"[INFO] 已加载论文: {args.file} ({len(paper_text)} 字符)\n")

    result = review_paper(paper_text, title)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_output(result))


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Commit**

```bash
git add paper_reviewer/main.py
git commit -m "feat(paper-reviewer): add CLI entry point with formatted output"
```

---

### Task 12: 集成测试

**Files:**
- Create: `tests/test_paper_reviewer.py`

**Interfaces:**
- Consumes: `paper_reviewer/main.py`, `paper_reviewer/graph.py`
- Produces: 测试通过/失败报告

- [ ] **Step 1: 编写测试文件**

```python
import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from paper_reviewer.state import ReviewState
from paper_reviewer.rubrics import calculate_weighted_score, score_to_decision
from paper_reviewer.graph import build_review_graph


class TestRubrics:
    def test_weighted_score_calculation(self):
        scores = {
            "originality": 80,
            "methodology": 70,
            "evidence": 75,
            "coherence": 85,
            "writing": 80,
        }
        result = calculate_weighted_score(scores)
        expected = 80 * 0.20 + 70 * 0.25 + 75 * 0.25 + 85 * 0.15 + 80 * 0.15
        assert result == round(expected, 1)

    def test_score_to_decision_accept(self):
        assert score_to_decision(85) == "Accept"

    def test_score_to_decision_minor(self):
        assert score_to_decision(70) == "Minor Revision"

    def test_score_to_decision_major(self):
        assert score_to_decision(55) == "Major Revision"

    def test_score_to_decision_reject(self):
        assert score_to_decision(40) == "Reject"


class TestState:
    def test_initial_state(self):
        state = ReviewState(
            paper="test",
            paper_title="test",
            language="zh",
            primary_discipline="",
            secondary_disciplines=[],
            research_paradigm="",
            methodology_type="",
            target_journal_tier="",
            reviewer_configs=[],
            eic_report=None,
            methodology_report=None,
            domain_report=None,
            perspective_report=None,
            devils_advocate_report=None,
            editorial_decision="",
            consensus_analysis=None,
            dimension_scores=None,
            revision_roadmap=None,
        )
        assert state["paper"] == "test"
        assert state["eic_report"] is None


class TestGraph:
    def test_graph_builds(self):
        """验证图能正确编译。"""
        app = build_review_graph()
        assert app is not None

    def test_graph_runs_end_to_end(self):
        """端到端测试：用一篇短论文运行完整审稿流程。"""
        app = build_review_graph()
        # 使用一篇极简论文（实际测试时替换为真实短论文）
        short_paper = """
        摘要：本研究探讨了人工智能在教育领域的应用。
        方法：采用问卷调查法，收集了200名学生的数据。
        结果：发现AI工具能显著提升学习效率。
        结论：建议在教学中推广AI工具。
        """
        initial_state = ReviewState(
            paper=short_paper,
            paper_title="AI教育应用测试论文",
            language="zh",
            primary_discipline="",
            secondary_disciplines=[],
            research_paradigm="",
            methodology_type="",
            target_journal_tier="",
            reviewer_configs=[],
            eic_report=None,
            methodology_report=None,
            domain_report=None,
            perspective_report=None,
            devils_advocate_report=None,
            editorial_decision="",
            consensus_analysis=None,
            dimension_scores=None,
            revision_roadmap=None,
        )
        result = app.invoke(initial_state)
        assert result["editorial_decision"] in ["Accept", "Minor Revision", "Major Revision", "Reject"]
        assert result["eic_report"] is not None
        assert result["devils_advocate_report"] is not None
        assert result["dimension_scores"] is not None
```

- [ ] **Step 2: 运行测试**

```bash
cd /c/Yechen_project/Agent-AI
pip install pytest
python -m pytest tests/test_paper_reviewer.py -v
```

- [ ] **Step 3: 修复任何失败的测试**

（根据测试结果修复）

- [ ] **Step 4: Commit**

```bash
git add tests/test_paper_reviewer.py
git commit -m "test(paper-reviewer): add unit + integration tests"
```

---

## 执行顺序建议

| 顺序 | Task | 依赖 |
|------|------|------|
| 1 | Task 1: 骨架 + 状态 | 无 |
| 2 | Task 2: System Prompts | 无（可与 Task 1 并行） |
| 3 | Task 3: Field Analyst | Task 1, 2 |
| 4 | Task 4-8: 5 个审稿人 | Task 1, 2（彼此可并行） |
| 5 | Task 9: Synthesizer | Task 3-8 |
| 6 | Task 10: 图组装 | Task 3-9 |
| 7 | Task 11: CLI | Task 10 |
| 8 | Task 12: 测试 | Task 11 |

Task 4-8（5 个审稿人）结构高度相似，可由子代理并行实现。