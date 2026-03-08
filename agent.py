import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TypedDict

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph


ROOT_DIR = Path(__file__).resolve().parent
MODEL_NAME = "gemini-3-flash-preview"
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
WORKER_SYSTEM_PROMPT = (
    "あなたは優秀なSREである。提供されたログから根本的な原因を推測し、"
    "それを解決するためのシェルコマンドを1つだけ提案せよ。"
    "実行環境はmacOSであるため、コマンドはmacOS標準ツールとBSD系sedの構文に対応させよ。"
    "修正対象の設定ファイルは ./nginx/nginx.conf のみとし、他のファイルは変更してはならない。"
    "grep -rl や find でリポジトリ全体を横断して書き換えるようなコマンドは禁止する。"
    "一時的な再起動では直らない設定エラーが含まれている可能性がある。"
    "ホストOS上から設定ファイルを書き換える必要がある場合は、sed等を用いて修正し、"
    "その後に再起動を行う一連のコマンドを組み立てよ。"
    "マークダウン記法(```bashなど)や説明文は一切含めず、"
    "そのまま実行可能な純粋なコマンド文字列のみを返せ。"
)


class AgentState(TypedDict):
    logs: str
    proposed_command: str
    execution_result: str


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


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


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
    return {
        "logs": combined_logs,
        "proposed_command": state.get("proposed_command", ""),
        "execution_result": state.get("execution_result", ""),
    }


def worker_node(state: AgentState) -> AgentState:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        return {
            "logs": state["logs"],
            "proposed_command": "",
            "execution_result": state.get("execution_result", ""),
        }

    model = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        google_api_key=api_key,
        temperature=0,
    )
    try:
        response = model.invoke(
            [
                ("system", WORKER_SYSTEM_PROMPT),
                (
                    "human",
                    "以下は Docker ベースの障害環境から取得したログである。"
                    "ホストOS上で実行可能な修復コマンドを1つだけ返せ。\n\n"
                    f"{state['logs']}",
                ),
            ]
        )
        proposed_command = _strip_command_text(_extract_text_from_content(response.content))
    except Exception as exc:
        proposed_command = ""
        return {
            "logs": state["logs"],
            "proposed_command": proposed_command,
            "execution_result": f"worker_node failed: {exc}",
        }
    return {
        "logs": state["logs"],
        "proposed_command": proposed_command,
        "execution_result": state.get("execution_result", ""),
    }


def executor_node(state: AgentState) -> AgentState:
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
    return {
        "logs": state["logs"],
        "proposed_command": state["proposed_command"],
        "execution_result": execution_result,
    }


builder = StateGraph(AgentState)
builder.add_node("sensor_node", sensor_node)
builder.add_node("worker_node", worker_node)
builder.add_node("executor_node", executor_node)
builder.add_edge(START, "sensor_node")
builder.add_edge("sensor_node", "worker_node")
builder.add_edge("worker_node", "executor_node")
builder.add_edge("executor_node", END)
app = builder.compile()


if __name__ == "__main__":
    if sys.version_info >= (3, 14):
        print(
            "[warn] Python 3.14+ is not fully supported by the current LangChain core stack. "
            "Python 3.12 or 3.13 is recommended."
        )
    initial_state: AgentState = {
        "logs": "",
        "proposed_command": "",
        "execution_result": "",
    }
    final_state = app.invoke(initial_state)
    _section("🤖 [PHASE 1] SENSOR NODE (ログの取得)")
    print(_tail_lines(final_state["logs"], count=10))
    print()

    _section("🧠 [PHASE 2] WORKER NODE (AIの推論結果)")
    print("【提案されたコマンド】:")
    print(final_state["proposed_command"] if final_state["proposed_command"] else "(no command proposed)")
    print()

    _section("⚡️ [PHASE 3] EXECUTOR NODE (コマンドの実行結果)")
    return_code, execution_output = _parse_execution_summary(final_state["execution_result"])
    if return_code is None:
        print("【実行ステータス】: 未実行または解析不能")
    else:
        status = "成功" if return_code == 0 else "失敗"
        print(f"【実行ステータス】: {status} (Return Code: {return_code})")
    print("【標準出力 / エラー出力】:")
    print(execution_output if execution_output else "(no output)")
    print()

    _section("🏁 ワークフロー完了")
