import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal, TypedDict

from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph


ROOT_DIR = Path(__file__).resolve().parent
# Inference from OpenAI's current official models page: gpt-5.2 is the latest
# flagship GPT model exposed for general API use at the time of writing.
MODEL_NAME = "gpt-5.2"
SENSOR_COMMAND = [
    "docker",
    "compose",
    "logs",
    "--tail=50",
    "nginx",
    "app",
    "db",
]
FALLBACK_CONTAINERS = ("target-nginx", "target-app", "target-db")
MAX_RETRIES = 3
WORKER_SYSTEM_PROMPT = (
    "あなたは世界トップクラスのSREである。提供されたログから根本原因を推測し、"
    "ホストOS上から実行可能な修復コマンドを1つだけ提案せよ。"
    "場当たり的な再起動だけでなく、必要であれば設定ファイルや環境変数ファイルを"
    "適切に修正したうえで再起動する一連のコマンドを組み立てよ。"
    "影響範囲を最小化し、無関係なファイルを変更してはならない。"
    "実行環境はmacOSであるため、コマンドはmacOS標準ツールとBSD系sedの構文に対応させよ。"
    "出力は、そのまま実行可能な純粋なコマンド文字列のみとし、"
    "マークダウンや説明文は一切含めてはならない。"
)
JUDGE_SYSTEM_PROMPT = (
    "あなたは厳格なインフラ監査役である。"
    "与えられたシェルコマンドが安全に実行できるかを審査せよ。"
    "特に以下を重視すること。"
    "1. break.sh や reset.sh など無関係なスクリプトを書き換えていないか。"
    "2. カレントディレクトリ全体に対する一括置換など影響範囲が広すぎないか。"
    "3. macOS の BSD 系 sed 構文に違反していないか。"
    "必ず JSON のみを返し、形式は "
    '{"is_approved": true|false, "judge_feedback": "..." } '
    "とせよ。承認時も judge_feedback に短い理由を入れよ。"
)


class AgentState(TypedDict):
    logs: str
    proposed_command: str
    execution_result: str
    retry_count: int
    judge_feedback: str
    is_approved: bool


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _format_completed_process(command: str, result: subprocess.CompletedProcess[str]) -> str:
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    sections = [
        f"$ {command}",
        f"[returncode] {result.returncode}",
        "[stdout]",
        stdout if stdout else "(empty)",
        "[stderr]",
        stderr if stderr else "(empty)",
    ]
    return "\n".join(sections)


def _strip_command_text(text: str) -> str:
    cleaned = text.strip()
    fence_match = re.match(r"^```(?:bash|sh)?\s*(.*?)```$", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    cleaned = cleaned.strip("`").strip()
    return cleaned.strip().splitlines()[0].strip() if cleaned.strip() else ""


def _extract_text_from_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for block in content:
            block_text = getattr(block, "text", None)
            if isinstance(block_text, str):
                text_parts.append(block_text)
                continue
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                text_parts.append(block["text"])
        return "\n".join(text_parts)
    return str(content)


def _tail_lines(text: str, count: int = 10) -> str:
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return "(no logs)"
    if len(lines) <= count:
        return "\n".join(lines)
    return "...\n" + "\n".join(lines[-count:])


def _parse_execution_summary(execution_result: str) -> tuple[int | None, str]:
    match = re.search(r"^\[returncode\]\s+(-?\d+)$", execution_result, flags=re.MULTILINE)
    return_code = int(match.group(1)) if match else None
    output_match = re.search(
        r"^\[stdout\]\n(.*?)\n\[stderr\]\n(.*)$",
        execution_result.strip(),
        flags=re.DOTALL | re.MULTILINE,
    )
    if not output_match:
        return return_code, execution_result.strip()

    stdout = output_match.group(1).strip()
    stderr = output_match.group(2).strip()
    combined_parts = []
    if stdout and stdout != "(empty)":
        combined_parts.append(stdout)
    if stderr and stderr != "(empty)":
        combined_parts.append(stderr)
    combined_output = "\n".join(combined_parts).strip()
    return return_code, combined_output if combined_output else "(no output)"


def _openai_chat() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    return ChatOpenAI(model=MODEL_NAME, api_key=api_key, temperature=0)


def _heuristic_judge(command: str) -> str:
    issues: list[str] = []
    stripped = command.strip()

    if not stripped:
        issues.append("コマンドが空である。実行可能な修復コマンドを提案すること。")

    if re.search(r"\b(break\.sh|reset\.sh)\b", stripped):
        issues.append("break.sh または reset.sh を変更対象に含めているため却下する。")

    if re.search(r"grep\s+-rl", stripped) or re.search(r"xargs\s+sed", stripped):
        issues.append("リポジトリ全体への横断置換に見えるため却下する。対象ファイルを明示すること。")

    if re.search(r"find\s+\.\b", stripped):
        issues.append("find によるディレクトリ全体走査が含まれており影響範囲が広すぎる。")

    if "sed -i " in stripped and "sed -i ''" not in stripped and "sed -i''" not in stripped:
        issues.append("macOS の BSD sed では sed -i に空文字バックアップ引数が必要である。")

    return " ".join(issues)


def _print_worker_section(retry_count: int, command: str) -> None:
    if retry_count == 0:
        _section("🧠 [PHASE 2] WORKER NODE (AIの推論結果)")
    else:
        _section(f"🔄 [RETRY {retry_count}] WORKER NODE (AIの再提案)")
    print("【提案されたコマンド】:")
    print(command if command else "(no command proposed)")
    print()


def _print_judge_section(is_approved: bool, judge_feedback: str) -> None:
    _section("⚖️ [PHASE 2.5] JUDGE NODE (監査と承認)")
    print(f"【ジャッジ判定】: {'承認' if is_approved else '却下'}")
    print("【フィードバック】:")
    print(judge_feedback if judge_feedback else "(no feedback)")
    print()


def sensor_node(state: AgentState) -> AgentState:
    result = subprocess.run(
        SENSOR_COMMAND,
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )

    log_chunks = [_format_completed_process(" ".join(SENSOR_COMMAND), result)]
    if result.returncode != 0:
        for container_name in FALLBACK_CONTAINERS:
            fallback = subprocess.run(
                ["docker", "logs", "--tail=50", container_name],
                capture_output=True,
                text=True,
                cwd=ROOT_DIR,
            )
            log_chunks.append(
                _format_completed_process(f"docker logs --tail=50 {container_name}", fallback)
            )

    combined_logs = "\n\n".join(log_chunks)
    _section("🤖 [PHASE 1] SENSOR NODE (ログの取得)")
    print(_tail_lines(combined_logs, count=10))
    print()
    return {
        "logs": combined_logs,
        "proposed_command": state.get("proposed_command", ""),
        "execution_result": state.get("execution_result", ""),
        "retry_count": state.get("retry_count", 0),
        "judge_feedback": state.get("judge_feedback", ""),
        "is_approved": state.get("is_approved", False),
    }


def worker_node(state: AgentState) -> AgentState:
    try:
        model = _openai_chat()
    except Exception as exc:
        proposed_command = ""
        _print_worker_section(state["retry_count"], proposed_command)
        return {
            "logs": state["logs"],
            "proposed_command": proposed_command,
            "execution_result": f"worker_node failed: {exc}",
            "retry_count": state["retry_count"],
            "judge_feedback": state.get("judge_feedback", ""),
            "is_approved": False,
        }

    user_prompt = (
        "以下は Docker ベースの障害環境から取得したログである。"
        "ホストOS上で実行可能な修復コマンドを1つだけ返せ。\n\n"
        f"{state['logs']}"
    )
    if state["retry_count"] > 0:
        user_prompt += (
            "\n\n前回あなたが提案したコマンドはジャッジに以下の理由で却下された。"
            "フィードバックを反映して安全なコマンドを再生成せよ。\n"
            f"前回の提案: {state['proposed_command']}\n"
            f"ジャッジの指摘: {state['judge_feedback']}"
        )

    try:
        response = model.invoke(
            [
                ("system", WORKER_SYSTEM_PROMPT),
                ("human", user_prompt),
            ]
        )
        proposed_command = _strip_command_text(_extract_text_from_content(response.content))
    except Exception as exc:
        proposed_command = ""
        _print_worker_section(state["retry_count"], proposed_command)
        return {
            "logs": state["logs"],
            "proposed_command": proposed_command,
            "execution_result": f"worker_node failed: {exc}",
            "retry_count": state["retry_count"],
            "judge_feedback": state.get("judge_feedback", ""),
            "is_approved": False,
        }

    _print_worker_section(state["retry_count"], proposed_command)
    return {
        "logs": state["logs"],
        "proposed_command": proposed_command,
        "execution_result": state.get("execution_result", ""),
        "retry_count": state["retry_count"],
        "judge_feedback": "",
        "is_approved": False,
    }


def judge_node(state: AgentState) -> AgentState:
    heuristic_feedback = _heuristic_judge(state["proposed_command"])
    if heuristic_feedback:
        _print_judge_section(False, heuristic_feedback)
        return {
            "logs": state["logs"],
            "proposed_command": state["proposed_command"],
            "execution_result": state.get("execution_result", ""),
            "retry_count": state["retry_count"],
            "judge_feedback": heuristic_feedback,
            "is_approved": False,
        }

    try:
        model = _openai_chat()
        response = model.invoke(
            [
                ("system", JUDGE_SYSTEM_PROMPT),
                (
                    "human",
                    "以下の修復コマンドを審査せよ。\n"
                    f"ログ:\n{state['logs']}\n\n"
                    f"提案コマンド:\n{state['proposed_command']}",
                ),
            ]
        )
        response_text = _extract_text_from_content(response.content).strip()
        json_match = re.search(r"\{.*\}", response_text, flags=re.DOTALL)
        payload = json.loads(json_match.group(0) if json_match else response_text)
        is_approved = bool(payload.get("is_approved", False))
        judge_feedback = str(payload.get("judge_feedback", "")).strip()
        if not judge_feedback:
            judge_feedback = "ジャッジ結果の説明が空であった。"
    except Exception as exc:
        is_approved = False
        judge_feedback = (
            "ジャッジ処理に失敗したため却下する。"
            f" 失敗理由: {exc}"
        )

    _print_judge_section(is_approved, judge_feedback)
    return {
        "logs": state["logs"],
        "proposed_command": state["proposed_command"],
        "execution_result": state.get("execution_result", ""),
        "retry_count": state["retry_count"],
        "judge_feedback": judge_feedback,
        "is_approved": is_approved,
    }


def increment_retry_node(state: AgentState) -> AgentState:
    return {
        "logs": state["logs"],
        "proposed_command": state["proposed_command"],
        "execution_result": state.get("execution_result", ""),
        "retry_count": state["retry_count"] + 1,
        "judge_feedback": state["judge_feedback"],
        "is_approved": state["is_approved"],
    }


def executor_node(state: AgentState) -> AgentState:
    _section("⚡️ [PHASE 3] EXECUTOR NODE (コマンドの実行結果)")
    command = state["proposed_command"].strip()
    if not command:
        if state.get("execution_result", "").startswith("worker_node failed:"):
            execution_result = state["execution_result"]
        else:
            execution_result = "No command was proposed by worker_node."
    else:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
        )
        execution_result = _format_completed_process(command, result)

    return_code, execution_output = _parse_execution_summary(execution_result)
    if return_code is None:
        print("【実行ステータス】: 未実行または解析不能")
    else:
        status = "成功" if return_code == 0 else "失敗"
        print(f"【実行ステータス】: {status} (Return Code: {return_code})")
    print("【標準出力 / エラー出力】:")
    print(execution_output if execution_output else "(no output)")
    print()

    return {
        "logs": state["logs"],
        "proposed_command": state["proposed_command"],
        "execution_result": execution_result,
        "retry_count": state["retry_count"],
        "judge_feedback": state["judge_feedback"],
        "is_approved": state["is_approved"],
    }


def should_execute(state: AgentState) -> Literal["execute", "retry", "end"]:
    if state["is_approved"]:
        return "execute"
    if state["retry_count"] < MAX_RETRIES:
        return "retry"
    return "end"


builder = StateGraph(AgentState)
builder.add_node("sensor_node", sensor_node)
builder.add_node("worker_node", worker_node)
builder.add_node("judge_node", judge_node)
builder.add_node("increment_retry_node", increment_retry_node)
builder.add_node("executor_node", executor_node)
builder.add_edge(START, "sensor_node")
builder.add_edge("sensor_node", "worker_node")
builder.add_edge("worker_node", "judge_node")
builder.add_conditional_edges(
    "judge_node",
    should_execute,
    {
        "execute": "executor_node",
        "retry": "increment_retry_node",
        "end": END,
    },
)
builder.add_edge("increment_retry_node", "worker_node")
builder.add_edge("executor_node", END)
app = builder.compile()


if __name__ == "__main__":
    if sys.version_info >= (3, 14):
        print(
            "[warn] Python 3.14+ is not fully supported by parts of the current LangChain stack. "
            "Python 3.12 or 3.13 is recommended."
        )

    initial_state: AgentState = {
        "logs": "",
        "proposed_command": "",
        "execution_result": "",
        "retry_count": 0,
        "judge_feedback": "",
        "is_approved": False,
    }
    final_state = app.invoke(initial_state)

    _section("🏁 ワークフロー完了")
    if final_state["is_approved"]:
        print("【最終結果】: ジャッジ承認後にコマンドを実行して終了")
    elif final_state["retry_count"] >= MAX_RETRIES:
        print(f"【最終結果】: リトライ上限 ({MAX_RETRIES}) に到達したためエスカレーションして終了")
    else:
        print("【最終結果】: 実行せず終了")
    print(f"【最終リトライ回数】: {final_state['retry_count']}")
    if final_state["judge_feedback"]:
        print("【最終ジャッジフィードバック】:")
        print(final_state["judge_feedback"])
