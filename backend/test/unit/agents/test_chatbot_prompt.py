from types import SimpleNamespace

from yuxi.agents.buildin.chatbot.prompt import PROMPT, build_prompt_with_context


def test_chatbot_prompt_prefers_complete_explanatory_paragraphs():
    assert "减少 bullet points" in PROMPT
    assert "完整的句子和段落" in PROMPT
    assert "详细的解释和背景信息" in PROMPT


def test_chatbot_prompt_declares_workspace_visibility_and_default_write_boundary():
    prompt = build_prompt_with_context(
        SimpleNamespace(
            workdir_path="/home/gem/user-data/projects/11111111-1111-4111-8111-111111111111",
            system_prompt="",
        )
    )

    assert "可以读取其他 Project 目录作为参考" in prompt
    assert "未经用户明确要求，不得在当前 Project Workdir 之外" in prompt
    assert "/home/gem/user-data/agents/skills/" in prompt
    assert "html:preview" not in prompt


def test_chatbot_prompt_injects_only_local_git_worktree_contract():
    prompt = build_prompt_with_context(
        SimpleNamespace(
            workdir_path="/home/gem/user-data/projects/project-id",
            system_prompt="",
            git_repositories=[
                {
                    "alias": "api",
                    "purpose": "后端 API",
                    "task_purpose": "实现退款",
                    "path": "/home/gem/user-data/projects/project-id/repos/api/worktrees/task",
                    "branch": "codex/task-abc",
                    "base_branch": "main",
                    "base_sha": "a" * 40,
                }
            ],
            project_git_enabled=True,
        )
    )

    assert "git -C <path>" in prompt
    assert "git_push_branch" in prompt
    assert "codex/task-abc" in prompt
    assert "private_key" not in prompt
    assert "remote_url" not in prompt
