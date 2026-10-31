"""Optional pre-tool guard: local readiness only, never scoring or network I/O."""
import argparse
import json
import re
import shlex
import sys
from pathlib import Path

from ..core import FaultlineError, Store, repo_root
from . import ci_handoff as handoff

GUIDANCE = ('Use the Faultline skill before this push. Resolve the actual PR target branch, fetch origin, '
            'and use the merge base of that branch and the final HEAD as the assessment base. '
            'Prepare focused context only where needed, assess the entire cumulative diff with noul-v1 '
            'within the existing spending limit, then publish using ci-submit --run <id> --threshold 0.50 '
            '--target-branch <branch> --repository <owner/repo>. Wait for published: true before retrying. '
            'If scoring cannot complete, explicitly publish ci-submit --full --head HEAD --target-branch <branch> '
            '--repository <owner/repo> --reason <reason>; this makes no Jev calls. Do not increase budgets or '
            'loop on failed publication. Commit and push must be separate tool calls. Never bypass a hook '
            'or change its target branch without the user\'s approval.')


def push_root(command, cwd):
    """Accept an explicit single-repository push; deny ambiguous push syntax.

    This is not a shell interpreter/security boundary. Aliases, scripts, MCP
    tools and existing terminal sessions may evade it; CI independently checks.
    """
    if not isinstance(command, str):
        raise FaultlineError('Unsupported shell input')
    try:
        tokens = shlex.split(command)
    except ValueError:
        if 'push' in command:
            raise FaultlineError('Cannot inspect push syntax; use a separate git push origin HEAD command') from None
        return None
    if 'push' not in tokens and not re.search(r'\bgit\b.*\bpush\b', command, re.S):
        return None
    if not any(Path(token).name == 'git' for token in tokens):
        if re.search(r'\bgit\b.*\bpush\b', command, re.S):
            raise FaultlineError('Wrapped pushes cannot be checked; use a separate git push origin HEAD command')
        return None
    if not tokens or Path(tokens[0]).name != 'git' or any(c in command for c in '\n;&|`$<>'):
        raise FaultlineError('Use separate commit and push tool calls; compound or wrapped pushes cannot be checked')
    root, index = Path(cwd), 1
    if tokens[index:index+1] == ['-C']:
        if len(tokens) <= index + 2:
            raise FaultlineError('Invalid git -C push')
        root = (root / tokens[index + 1]).resolve()
        index += 2
    if tokens[index:index+1] != ['push']:
        raise FaultlineError('Use git push origin HEAD (optional git -C directory) for the readiness hook')
    args = tokens[index+1:]
    flags = {'-u', '--set-upstream', '-f', '--force', '--force-with-lease', '--no-verify', '--porcelain', '--verbose', '-v'}
    refs = []
    for arg in args:
        if arg in flags or arg.startswith('--force-with-lease='):
            continue
        if arg.startswith('-'):
            raise FaultlineError('This push option cannot be checked; use an explicit single branch push')
        refs.append(arg)
    if len(refs) != 2 or refs[0] != 'origin':
        raise FaultlineError('Use an explicit single branch push: git push origin HEAD')
    source, *destination = refs[1].lstrip('+').split(':')
    if len(destination) > 1 or not source:
        raise FaultlineError('Unsupported push refspec')
    if destination:
        handoff.branch_name(destination[0].removeprefix('refs/heads/'))
        if destination[0].startswith('refs/') and not destination[0].startswith('refs/heads/'):
            raise FaultlineError('Only branch pushes are supported by this hook')
    root = repo_root(root)
    if handoff.origin(root, push=True) != handoff.origin(root):
        raise FaultlineError('Push destination differs from the publication repository')
    if handoff.revision(root, source) != handoff.revision(root):
        raise FaultlineError('The push source is not the checked-out HEAD; assess and publish that branch first')
    return root


def check(data, agent, target_branch):
    command = data.get('command') if agent == 'cursor' else data.get('tool_input', {}).get('command')
    tool_input = data.get('tool_input', {})
    cwd = tool_input.get('cwd') or tool_input.get('workdir') or data.get('cwd')
    if not cwd:
        raise FaultlineError('Hook input has no working directory')
    root = push_root(command, cwd)
    if root is None:
        return
    try:
        handoff.ready(Store(root), target_branch)
    except (FaultlineError, OSError, KeyError, ValueError, TypeError, AttributeError):
        raise FaultlineError('No current, confirmed publication for this HEAD and target branch. ' + GUIDANCE) from None


def response(agent, message=None):
    if agent == 'cursor':
        return {'permission': 'deny', 'user_message': message, 'agent_message': message} if message else {'permission': 'allow'}
    # Empty success defers to the host's normal approval/permission rules.
    return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                   'permissionDecisionReason': message}} if message else {}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agent', choices=('cursor', 'claude', 'codex'), required=True)
    parser.add_argument('--target-branch', required=True)
    args = parser.parse_args(argv)
    message = None
    try:
        data = handoff.json_data(sys.stdin.buffer.read(65537), 65536)
        check(data, args.agent, handoff.branch_name(args.target_branch))
    except (FaultlineError, OSError, KeyError, TypeError, ValueError, AttributeError) as exc:
        message = str(exc) if isinstance(exc, FaultlineError) else 'Faultline could not inspect this push. Check the hook configuration.'
    print(json.dumps(response(args.agent, message)))
    return 0
