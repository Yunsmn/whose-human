import json
import subprocess

import pytest

from model import api_corpus
from model import cli_corpus as cli


def test_message_replaces_visible_page_instruction():
    prompt = api_corpus.Prompt("site1", "old", "article\n\nvisible page label")
    updated = cli.cli_prompt(prompt)
    assert updated.user_message == f"article\n\n{cli.DIRECT_INSTRUCTION}"
    assert "submit" not in updated.user_message.lower()
    assert updated.prompt_id != api_corpus.prompt_id("site1", prompt.user_message)


def test_claude_command_variants(tmp_path):
    assert cli.claude_command("claude", "haiku", "prompt", "default") == [
        "claude",
        "-p",
        "--model",
        "haiku",
        "--tools",
        "",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--output-format",
        "json",
        "prompt",
    ]
    assert cli.claude_command("claude", "haiku", "prompt", "minimal") == [
        "claude",
        "-p",
        "--model",
        "haiku",
        "--tools",
        "",
        "--no-session-persistence",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--output-format",
        "json",
        "--system-prompt",
        cli.MINIMAL_SYSTEM_PROMPT,
        "prompt",
    ]


def test_codex_command_variants_and_minimal_file(tmp_path):
    base = [
        "codex",
        "exec",
        "-m",
        "gpt",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--ephemeral",
        "--ignore-rules",
        "--ignore-user-config",
        "-C",
        str(tmp_path),
        "--json",
    ]
    assert cli.codex_command("codex", "gpt", "prompt", tmp_path, "default") == base + ["prompt"]
    command = cli.codex_command("codex", "gpt", "prompt", tmp_path, "minimal")
    path = tmp_path / "minimal-system-prompt.txt"
    assert command == base + ["-c", f"model_instructions_file='{path}'", "prompt"]
    assert path.read_text() == cli.MINIMAL_SYSTEM_PROMPT


def test_parse_claude_success_and_errors():
    reply = cli.parse_claude(
        json.dumps(
            {
                "is_error": False,
                "result": "answer",
                "stop_reason": "end_turn",
                "session_id": "s",
                "modelUsage": {"m": {"inputTokens": 2, "outputTokens": 8}},
            }
        )
    )
    assert reply == api_corpus.Reply("answer", "end_turn", "m", 2, 8, "s")
    with pytest.raises(cli.CliError, match="bad result"):
        cli.parse_claude('{"is_error":true,"result":"bad result"}')
    with pytest.raises(cli.CliError, match="unparsable"):
        cli.parse_claude("not json")


def test_parse_codex_uses_last_agent_message_and_usage():
    events = [
        {"type": "thread.started", "thread_id": "t"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "first"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "last"}},
        {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 3}},
    ]
    reply = cli.parse_codex("\n".join(map(json.dumps, events)))
    assert reply == api_corpus.Reply("last", "end_turn", None, 12, 3, "t")


@pytest.mark.parametrize(
    "event", [{"type": "turn.failed", "message": "failed"}, {"type": "error", "message": "oops"}]
)
def test_parse_codex_failure_events(event):
    with pytest.raises(cli.CliError):
        cli.parse_codex(json.dumps(event))


def test_parse_codex_requires_agent_message():
    with pytest.raises(cli.CliError, match="no agent_message"):
        cli.parse_codex('{"type":"turn.completed"}')


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, cwd, timeout):
        self.calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            json.dumps(
                {
                    "is_error": False,
                    "result": "answer",
                    "stop_reason": "end_turn",
                    "session_id": "session",
                    "modelUsage": {},
                }
            ),
            "",
        )


def test_run_writes_rows_resumes_errors_and_caps(tmp_path):
    models = [api_corpus.ModelSpec("m", "anthropic", "model", True)]
    prompts = [api_corpus.Prompt("site1", "p1", "article\n\nold")]
    runner = FakeRunner()
    result = cli.run_collection(
        models,
        prompts,
        2,
        ["default", "minimal"],
        tmp_path,
        runner,
        executable_map={"anthropic": "claude"},
        version_map={"anthropic": "v"},
        max_requests=2,
    )
    rows = [json.loads(row) for row in next(tmp_path.glob("*.jsonl")).read_text().splitlines()]
    assert result["_run"]["attempted"] == 2 and len(runner.calls) == 2
    assert rows[0]["id"] == "m:p1:default:0"
    assert rows[0]["harness"] == "claude-code" and rows[0]["cli_version"] == "v"
    assert rows[0]["text"] == "answer" and rows[0]["error"] is None
    runner2 = FakeRunner()
    resumed = cli.run_collection(
        models,
        prompts,
        2,
        ["default", "minimal"],
        tmp_path,
        runner2,
        executable_map={"anthropic": "claude"},
        version_map={"anthropic": "v"},
    )
    assert resumed["m"]["skipped"] == 2 and len(runner2.calls) == 2  # cap left 2 of 4 for the resumed run


def test_error_rows_retry_and_malformed_lines_warn(tmp_path, capsys):
    target = tmp_path / "corpus-old.jsonl"
    target.write_text(
        '{"name":"m","prompt_id":"p","condition":"default","sample_idx":0,"error":"old"}\n{malformed\n',
        encoding="utf-8",
    )
    model = api_corpus.ModelSpec("m", "anthropic", "model", True)
    prompt = api_corpus.Prompt("site1", "p", "article\n\nold")
    runner = FakeRunner()
    result = cli.run_collection(
        [model],
        [prompt],
        1,
        ["default"],
        tmp_path,
        runner,
        executable_map={"anthropic": "claude"},
        version_map={"anthropic": "v"},
    )
    assert result["_run"]["attempted"] == 1
    assert len(runner.calls) == 1
    assert "corpus-old.jsonl:2: malformed line" in capsys.readouterr().err


def test_dry_run_makes_no_runner_calls(monkeypatch, capsys):
    runner = FakeRunner()
    monkeypatch.setattr(cli, "resolve_preflight", lambda models: {"anthropic": "claude"})
    assert cli.main(["--dry-run", "--models", "claude-haiku-5-5", "--sites", "site1"], runner=runner) == 0
    assert not runner.calls
    assert "prompt_id" in capsys.readouterr().out


def test_preflight_missing_cli_and_google():
    with pytest.raises(cli.PreflightError, match="not found"):
        cli.resolve_preflight([api_corpus.ModelSpec("m", "anthropic", "x", True)], which=lambda _: None)
    with pytest.raises(cli.PreflightError, match="Gemini CLI collector not implemented"):
        cli.resolve_preflight([api_corpus.ModelSpec("g", "google", "gemini", True)])


def test_parse_claude_counts_cached_input_tokens():
    stdout = json.dumps(
        {
            "is_error": False,
            "result": "ok",
            "modelUsage": {
                "claude-haiku-5-5": {
                    "inputTokens": 2,
                    "cacheReadInputTokens": 649,
                    "cacheCreationInputTokens": 3077,
                    "outputTokens": 86,
                }
            },
        }
    )
    reply = cli.parse_claude(stdout)
    assert reply.input_tokens == 3728 and reply.output_tokens == 86


def test_parse_codex_flags_non_message_items():
    events = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "ls"}},
        {"type": "item.completed", "item": {"type": "agent_message", "text": "answer"}},
        {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}},
    ]
    reply = cli.parse_codex("\n".join(json.dumps(event) for event in events))
    assert reply.text == "answer" and reply.stop_reason == "end_turn+1_items"


def test_codex_minimal_path_is_a_toml_literal_string(tmp_path):
    import tomllib

    argv = cli.codex_command("codex", "m", "prompt", tmp_path, "minimal")
    value = argv[argv.index("-c") + 1]
    assert tomllib.loads(value)["model_instructions_file"] == str(tmp_path / "minimal-system-prompt.txt")
    windows = "C:\\Users\\tester\\AppData\\Local\\Temp\\tmpab\\minimal-system-prompt.txt"
    assert tomllib.loads(f"model_instructions_file='{windows}'")["model_instructions_file"] == windows


def test_windows_claude_exe_path_uses_the_claude_parser(tmp_path):
    runner = FakeRunner()
    result = cli.run_collection(
        [api_corpus.ModelSpec("m", "anthropic", "model", True)],
        [api_corpus.Prompt("site1", "p1", "article\n\nSummarize")],
        1,
        ["default"],
        tmp_path,
        runner,
        executable_map={"anthropic": "C:\\Users\\tester\\.local\\bin\\claude.EXE"},
        version_map={"anthropic": "v"},
    )
    row = json.loads(next(tmp_path.glob("*.jsonl")).read_text())
    assert result["m"]["errors"] == 0 and row["text"] == "answer" and row["error"] is None


def test_failed_codex_exit_records_the_json_error():
    stdout = json.dumps({"type": "turn.failed", "error": {"message": "model is not supported"}})

    def runner(argv, cwd, timeout):
        return subprocess.CompletedProcess(argv, 1, stdout, "Reading additional input from stdin...")

    with pytest.raises(cli.CliError, match="status 1: .*model is not supported"):
        cli._invoke(runner, ["codex"], None, 5, cli.parse_codex)
