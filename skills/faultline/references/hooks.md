# Optional push readiness hooks

These hooks return instructions to the agent when a push has no confirmed Faultline decision. They do not gather source, call Jev, run tests, publish, or push. The agent follows the [CI workflow](handoff.md) within the user's existing authorization and budget.

## Install deliberately

First install the publisher/PR workflow and verify a manual `ci-submit --full` publication. Choose the actual target branch and locate this installed skill's absolute path.

| Agent | Template | Merge into |
| --- | --- | --- |
| Cursor | [cursor.json](../assets/hooks/cursor.json) | `.cursor/hooks.json` |
| Claude Code | [claude.json](../assets/hooks/claude.json) | `.claude/settings.local.json` (or reviewed project `settings.json`) |
| Codex | [codex.json](../assets/hooks/codex.json) | `.codex/hooks.json` |

Back up the destination if it exists. **Append only the Faultline hook entry to its existing event array**; preserve all other hooks and settings. Create a new file from the template only when no file exists. Replace `<FAULTLINE_SKILL_PATH>` with the absolute installed skill directory and `main` with the actual target branch. Do not commit a teammate's machine-specific path. On skill relocation or upgrade, verify the path again.

Restart/reload the agent and review its hook settings. Codex requires explicit trust for non-managed hooks through `/hooks`; changed definitions need renewed review. Review repository trust and command execution prompts in Cursor and Claude Code too. A template is not evidence that a hook is active. Use the host's hook diagnostics to verify it, without attempting an actual push.

The templates use supported synchronous pre-tool protocols: Cursor `beforeShellExecution`, Claude Code and Codex `PreToolUse` with the `Bash` matcher. One bundled `scripts/hook.py` translates the input/output. Successful Claude/Codex checks defer to existing permission rules; they do not grant push authorization. Cursor's hook is configured to fail closed.

## When a push is blocked

1. Resolve the actual PR target; refresh `origin/<target>` and compute its merge base with the final committed `HEAD`. Keep commit and push operations separate.
2. Use the Faultline skill to prepare/assess the **whole cumulative diff**, with focused context if needed and the existing spending ceiling. Use `noul-v1` for export; do not substitute Choice scores.
3. Publish with `ci-submit --run <id> --threshold 0.50 --target-branch <target> --repository <owner/repo>` and wait for `published: true`. If assessment cannot complete, explicitly publish `--full --head HEAD --reason '...'` instead.
4. Retry the separate push. Matching readiness uses no network or inference. Publication failure is a blocker to report, not a reason to loop, increase spending or bypass the hook.

An authorized push with this opt-in hook permits its decision handoff within the configured workflow and existing budget. It does not authorize unrelated workflow changes, comments, test execution locally, or a larger budget. If scoring lacks authorization, use the explicit full-execution handoff rather than spending.

Use an explicit single-branch command such as `git push origin HEAD`, optionally with `-u`, `--force-with-lease`, or `git -C <checkout>`. The hook rejects compound commit/push commands and ambiguous refspecs. It does not parse arbitrary shell programs, aliases, scripts, MCP tools or writes to existing terminal sessions. Hooks cannot guarantee interception. CI always checks independently and falls back fully when no matching publication exists.

Local readiness expires with the published artifact and binds the repository, target, merge base, head and reviewed execution configuration. A local checksum detects accidental modification; it is not a signature or a security boundary. Retargeting needs an updated hook argument and publication. A target branch moving remotely can escape an offline check, but CI calculates the authoritative event merge base again.

Official protocol references: [Cursor](https://cursor.com/docs/hooks), [Claude Code](https://code.claude.com/docs/en/hooks), [Codex](https://learn.chatgpt.com/docs/hooks). GitHub retrieval uses the [Actions artifact API](https://docs.github.com/en/rest/actions/artifacts).
