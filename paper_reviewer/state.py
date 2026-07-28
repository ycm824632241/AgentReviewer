import operator
from typing import Annotated, TypedDict, List, Optional, Literal

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
    # RAG 索引（Field Analyst 节点构建，后续节点使用）
    rag_index: object
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
    synthesized_round: Optional[int]   # 生成当前综合结论的轮次
    # ── Rebuttal 环节新增字段 ──
    round_number: int                   # 当前轮次，1-based
    rebuttal_text: Optional[str]        # 作者申诉正文
    rebuttal_target: Optional[str]     # "eic"/"methodology"/"domain"/"perspective"/"devils_advocate"/"all"/None
    rebuttal_history: Annotated[List[dict], operator.add]  # [{round, target, text, persuasion, adjustment}]
