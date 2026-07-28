"""
Multi-Agent Debate System using AutoGen-style orchestration.

Two AI agents debate a topic from opposing sides, moderated by a judge
who declares a winner and synthesizes the key arguments.

Usage:
    python agent.py --topic "AI will eliminate more jobs than it creates"
    python agent.py --topic "Remote work is better than office work" --rounds 3
"""

import argparse
import os
import sys

import httpx

# 强制 UTF-8 输出（解决 Windows 中文乱码）
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

load_dotenv()

# MiMo API configuration (OpenAI-compatible)
MIMO_BASE_URL = os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
MIMO_MODEL_DEBATER = os.getenv("MIMO_MODEL_DEBATER", "mimo-v2.5-pro")
MIMO_MODEL_JUDGE = os.getenv("MIMO_MODEL_JUDGE", "mimo-v2.5-pro")
MIMO_PROXY = os.getenv("MIMO_PROXY", "http://127.0.0.1:7897")


def _make_http_client() -> httpx.Client:
    """Create httpx client with proxy and SSL settings."""
    return httpx.Client(
        proxy=MIMO_PROXY if MIMO_PROXY else None,
        verify=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
    )


class DebateAgent:
    def __init__(self, name: str, position: str, expertise: str):
        self.name = name
        self.position = position
        self.expertise = expertise
        self.llm = ChatOpenAI(
            model=MIMO_MODEL_DEBATER,
            base_url=MIMO_BASE_URL,
            api_key=MIMO_API_KEY,
            temperature=0.6,
            http_client=_make_http_client(),
            http_async_client=httpx.AsyncClient(
                proxy=MIMO_PROXY if MIMO_PROXY else None,
                verify=True,
                timeout=httpx.Timeout(60.0, connect=15.0),
            ),
        )
        self.arguments = []

    def make_argument(self, topic: str, round_num: int, opponent_last_arg: str = "") -> str:
        system_msg = f"""You are {self.name}, a {self.expertise}.
You are arguing {self.position} on this topic.
Make compelling, evidence-based arguments. Be direct and persuasive.
Keep response under 150 words. Round {round_num}.

IMPORTANT: Respond entirely in Chinese (中文)."""

        if opponent_last_arg:
            user_msg = f"Topic: {topic}\n\nYour opponent just said: '{opponent_last_arg}'\n\nRespond and advance your argument (请用中文回答):"
        else:
            user_msg = f"Topic: {topic}\n\nMake your opening argument for {self.position.upper()} (请用中文回答):"

        response = self.llm.invoke([
            SystemMessage(content=system_msg),
            HumanMessage(content=user_msg),
        ])
        argument = response.content
        self.arguments.append(argument)
        return argument


class DebateJudge:
    def __init__(self):
        self.llm = ChatOpenAI(
            model=MIMO_MODEL_JUDGE,
            base_url=MIMO_BASE_URL,
            api_key=MIMO_API_KEY,
            temperature=0,
            http_client=_make_http_client(),
            http_async_client=httpx.AsyncClient(
                proxy=MIMO_PROXY if MIMO_PROXY else None,
                verify=True,
                timeout=httpx.Timeout(60.0, connect=15.0),
            ),
        )

    def evaluate(self, topic: str, pro_agent: DebateAgent, con_agent: DebateAgent) -> dict:
        pro_args = "\n\n".join(f"Round {i+1}: {a}" for i, a in enumerate(pro_agent.arguments))
        con_args = "\n\n".join(f"Round {i+1}: {a}" for i, a in enumerate(con_agent.arguments))

        response = self.llm.invoke([
            SystemMessage(content="""You are an impartial debate judge. Evaluate both sides fairly.
Return a structured verdict with: winner, score (out of 10 each), strongest argument per side, key insights, and balanced synthesis conclusion.

IMPORTANT: Respond entirely in Chinese (中文)."""),
            HumanMessage(content=f"""Topic: "{topic}"

PRO arguments ({pro_agent.name}):
{pro_args}

CON arguments ({con_agent.name}):
{con_args}

Provide your verdict (请用中文作答):"""),
        ])
        return {"verdict": response.content}


def run_debate(topic: str, rounds: int = 2) -> None:
    pro = DebateAgent(
        name="Dr. Alex Chen",
        position="FOR",
        expertise="technology economist and AI researcher"
    )
    con = DebateAgent(
        name="Prof. Sarah Martinez",
        position="AGAINST",
        expertise="labor economist and social policy expert"
    )
    judge = DebateJudge()

    print(f"\n{'='*60}")
    print(f"[DEBATE] {topic}")
    print(f"{'='*60}")
    print(f"[FOR]  {pro.name} ({pro.expertise})")
    print(f"[AGAINST] {con.name} ({con.expertise})")
    print(f"[ROUNDS] {rounds}")
    print("=" * 60)

    last_con_arg = ""
    last_pro_arg = ""

    for round_num in range(1, rounds + 1):
        print(f"\n--- Round {round_num} ---\n")

        pro_arg = pro.make_argument(topic, round_num, last_con_arg)
        print(f"[FOR] {pro.name}:")
        print(pro_arg)

        con_arg = con.make_argument(topic, round_num, pro_arg)
        print(f"\n[AGAINST] {con.name}:")
        print(con_arg)

        last_pro_arg = pro_arg
        last_con_arg = con_arg

    print(f"\n{'='*60}")
    print("[JUDGE'S VERDICT]")
    print("=" * 60)
    verdict = judge.evaluate(topic, pro, con)
    print(verdict["verdict"])


def main():
    parser = argparse.ArgumentParser(description="Multi-Agent Debate System")
    parser.add_argument("--topic", default="AI will create more jobs than it eliminates over the next decade", help="Debate topic")
    parser.add_argument("--rounds", type=int, default=2, help="Number of debate rounds (1-4)")
    args = parser.parse_args()

    rounds = max(1, min(4, args.rounds))
    run_debate(args.topic, rounds)


if __name__ == "__main__":
    main()
