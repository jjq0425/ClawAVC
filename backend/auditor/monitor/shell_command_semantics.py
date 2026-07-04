from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Optional, Sequence
from urllib.parse import urlparse

ResourceKind = Literal["file", "directory", "network", "process", "unknown"]
InferenceStatus = Literal["resolved", "partial", "unresolved"]


@dataclass(frozen=True)
class ShellBehavior:
    resource_kind: ResourceKind
    identifier: str
    action: str
    inference_status: InferenceStatus
    reason: str
    command: str


@dataclass(frozen=True)
class ShellAnalysis:
    command: str
    behaviors: List[ShellBehavior]
    overall_status: InferenceStatus
    notes: List[str]


SHELL_OPERATORS = {"|", "||", "&&", ";", "&"}
REDIRECT_READ = {"<"}
REDIRECT_WRITE = {">", ">>", "1>", "1>>", "2>", "2>>"}


def _tokenize(command: str) -> List[str]:
    try:
        lexer = shlex.shlex(
            command,
            posix=True,
            punctuation_chars="|&;<>",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except (TypeError, ValueError):
        try:
            return shlex.split(command)
        except ValueError:
            return command.split()


def _command_name(token: str) -> str:
    return Path(token).name.lower()


def _is_assignment(token: str) -> bool:
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token) is not None


def _looks_like_path(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    if token in {".", ".."} or token.startswith(("/", "./", "../", "~")):
        return True
    if "/" in token:
        return True
    return bool(
        re.search(
            r"\.(md|txt|json|py|csv|pdf|docx?|xlsx?|ya?ml|xml|sh|c|cc|cpp|h|log|tmp)$",
            token,
            re.IGNORECASE,
        )
    )


def _looks_like_network_identifier(token: str) -> bool:
    if not token or token.startswith("-"):
        return False
    parsed = urlparse(token)
    if parsed.scheme in {"http", "https", "ftp", "ssh", "git"} and (
        parsed.netloc or parsed.path
    ):
        return True
    if "@" in token and ":" in token:
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}(:\d+)?(/.*)?", token))


def _is_remote_path(token: str) -> bool:
    return bool(re.fullmatch(r"[^/\s@:]+@?[^/\s@:]+:.*", token))


def _resolve_path(raw_path: str, workdir: Optional[str]) -> str:
    if not raw_path:
        return str(Path(workdir or "."))
    if raw_path in {".", ".."}:
        return str(Path(workdir or ".") / raw_path)
    if "$" in raw_path or "`" in raw_path:
        return raw_path
    path = Path(raw_path)
    if path.is_absolute() or str(path).startswith("~"):
        return str(path)
    if workdir:
        return str(Path(workdir) / path)
    return str(path)


def _status_for_identifier(identifier: str) -> InferenceStatus:
    if re.search(r"`[^`]+`|\$\([^)]*\)|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", identifier):
        return "unresolved"
    if any(ch in identifier for ch in ["*", "?", "[", "]"]):
        return "partial"
    return "resolved"


def _merge_status(*statuses: InferenceStatus) -> InferenceStatus:
    if "unresolved" in statuses:
        return "unresolved"
    if "partial" in statuses:
        return "partial"
    return "resolved"


def _behavior(
    kind: ResourceKind,
    identifier: str,
    action: str,
    status: InferenceStatus,
    reason: str,
    command: str,
) -> ShellBehavior:
    return ShellBehavior(
        resource_kind=kind,
        identifier=identifier,
        action=action,
        inference_status=_merge_status(status, _status_for_identifier(identifier)),
        reason=reason,
        command=command,
    )


def _split_segments(tokens: Sequence[str]) -> List[List[str]]:
    segments: List[List[str]] = []
    current: List[str] = []
    for token in tokens:
        if token in SHELL_OPERATORS:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    return segments


def _redirection_behaviors(
    tokens: Sequence[str],
    workdir: Optional[str],
    command: str,
) -> List[ShellBehavior]:
    behaviors: List[ShellBehavior] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        target: Optional[str] = None
        action: Optional[str] = None

        if token in REDIRECT_READ and index + 1 < len(tokens):
            target = tokens[index + 1]
            action = "read"
            index += 2
        elif token in REDIRECT_WRITE and index + 1 < len(tokens):
            target = tokens[index + 1]
            action = "write"
            index += 2
        elif token.startswith((">>", ">")) and len(token) > 1:
            target = token.lstrip(">")
            action = "write"
            index += 1
        elif token.startswith("<") and len(token) > 1:
            target = token.lstrip("<")
            action = "read"
            index += 1
        else:
            index += 1

        if target and action:
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(target, workdir),
                    action,
                    "resolved",
                    "shell redirection",
                    command,
                )
            )
    return behaviors


def _strip_redirections(tokens: Sequence[str]) -> List[str]:
    stripped: List[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in REDIRECT_READ or token in REDIRECT_WRITE:
            index += 2
            continue
        if token.startswith((">", "<")) and len(token) > 1:
            index += 1
            continue
        stripped.append(token)
        index += 1
    return stripped


def _option_values(tokens: Sequence[str], option_names: Sequence[str]) -> List[str]:
    values: List[str] = []
    names = set(option_names)
    for index, token in enumerate(tokens):
        if token in names and index + 1 < len(tokens):
            values.append(tokens[index + 1])
        for name in names:
            prefix = name + "="
            if token.startswith(prefix):
                values.append(token[len(prefix) :])
    return values


def _path_args(tokens: Sequence[str]) -> List[str]:
    return [
        token
        for token in tokens
        if _looks_like_path(token)
        and token not in REDIRECT_READ
        and token not in REDIRECT_WRITE
        and not _is_remote_path(token)
    ]


def _network_args(tokens: Sequence[str]) -> List[str]:
    return [token for token in tokens if _looks_like_network_identifier(token)]


def _skip_wrappers(tokens: Sequence[str]) -> List[str]:
    current = list(tokens)
    while current:
        cmd = _command_name(current[0])
        if cmd in {"env", "time", "timeout", "nice", "nohup"}:
            current = current[1:]
            while current and (_is_assignment(current[0]) or current[0].startswith("-")):
                current = current[1:]
            continue
        if cmd == "sudo":
            current = current[1:]
            while current and current[0].startswith("-"):
                current = current[1:]
            continue
        break
    while current and _is_assignment(current[0]):
        current = current[1:]
    return current


def _nested_shell_command(tokens: Sequence[str]) -> Optional[str]:
    if "-c" not in tokens:
        return None
    index = tokens.index("-c")
    if index + 1 >= len(tokens):
        return None
    return tokens[index + 1]


def _analyze_segment(
    segment_tokens: Sequence[str],
    *,
    workdir: Optional[str],
    original_command: str,
    inherited_status: InferenceStatus,
) -> ShellAnalysis:
    notes: List[str] = []
    behaviors = _redirection_behaviors(segment_tokens, workdir, original_command)
    stripped_tokens = _strip_redirections(segment_tokens)
    privileged_wrapper = bool(stripped_tokens and _command_name(stripped_tokens[0]) == "sudo")
    if privileged_wrapper:
        notes.append("sudo privilege wrapper")
        behaviors.append(
            _behavior(
                "process",
                "sudo",
                "execute",
                "partial",
                "sudo privilege wrapper",
                original_command,
            )
        )
    tokens = _skip_wrappers(stripped_tokens)
    if not tokens:
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    cmd = _command_name(tokens[0])
    args = list(tokens[1:])
    path_tokens = _path_args(args)
    network_tokens = _network_args(args)

    if cmd in {"sh", "bash", "zsh"}:
        nested = _nested_shell_command(args)
        if nested:
            nested_analysis = analyze_shell_command(nested, workdir=workdir)
            notes.append("nested shell command parsed with partial confidence")
            behaviors.extend(
                ShellBehavior(
                    b.resource_kind,
                    b.identifier,
                    b.action,
                    _merge_status("partial", b.inference_status),
                    "nested shell: " + b.reason,
                    b.command,
                )
                for b in nested_analysis.behaviors
            )
        else:
            behaviors.append(
                _behavior(
                    "process",
                    cmd,
                    "execute",
                    "unresolved",
                    "shell interpreter without explicit -c payload",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    if cmd in {"curl", "wget", "http", "https"}:
        output_options = ["-o", "--output"]
        if cmd == "wget":
            output_options.extend(["-O", "--output-document"])
        output_targets = set(_option_values(args, output_options))
        upload_sources = set(_option_values(args, ["-T", "--upload-file"]))
        network_targets = [
            token
            for token in network_tokens
            if token not in output_targets and token not in upload_sources
        ]
        for identifier in network_targets or [cmd]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    "connect",
                    "resolved" if network_tokens else "partial",
                    f"{cmd} network client",
                    original_command,
                )
            )
        for target in output_targets:
            if target != "-":
                behaviors.append(
                    _behavior(
                        "file",
                        _resolve_path(target, workdir),
                        "write",
                        "partial",
                        f"{cmd} output target",
                        original_command,
                    )
                )
        for target in _option_values(args, ["-T", "--upload-file"]):
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(target, workdir),
                    "read",
                    "partial",
                    f"{cmd} upload source",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd in {"ssh", "sftp"}:
        for identifier in network_tokens or [next((arg for arg in args if not arg.startswith("-")), cmd)]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    "connect",
                    "partial",
                    f"{cmd} remote session",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    if cmd in {"scp", "rsync"}:
        remote_tokens = [token for token in args if _is_remote_path(token) or _looks_like_network_identifier(token)]
        for identifier in remote_tokens or [cmd]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    "connect",
                    "partial",
                    f"{cmd} remote transfer",
                    original_command,
                )
            )
        local_paths = _path_args(args)
        if local_paths:
            for local in local_paths[:-1]:
                behaviors.append(
                    _behavior(
                        "file",
                        _resolve_path(local, workdir),
                        "read",
                        "partial",
                        f"{cmd} transfer local source",
                        original_command,
                    )
                )
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(local_paths[-1], workdir),
                    "write",
                    "partial",
                    f"{cmd} transfer local destination",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    if cmd == "git":
        for identifier in network_tokens or ["git-remote"]:
            behaviors.append(
                _behavior(
                    "network",
                    identifier,
                    "connect",
                    "partial",
                    "git may contact remote repository",
                    original_command,
                )
            )
        if len(args) >= 2 and args[0] == "clone":
            dest = path_tokens[-1] if path_tokens else (workdir or ".")
            behaviors.append(
                _behavior(
                    "directory",
                    _resolve_path(dest, workdir),
                    "create",
                    "partial",
                    "git clone creates or updates worktree",
                    original_command,
                )
            )
        elif workdir:
            behaviors.append(
                _behavior(
                    "directory",
                    workdir,
                    "write",
                    "partial",
                    "git may update repository metadata or worktree",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    if cmd in {"pip", "pip3", "npm", "pnpm", "yarn", "docker"}:
        behaviors.append(
            _behavior(
                "network",
                cmd,
                "connect",
                "partial",
                f"{cmd} may fetch remote package or image metadata",
                original_command,
            )
        )
        if workdir:
            behaviors.append(
                _behavior(
                    "directory",
                    workdir,
                    "write",
                    "partial",
                    f"{cmd} may update local environment or cache",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    if cmd in {"ls", "find", "pwd", "tree", "du"}:
        target = path_tokens[0] if path_tokens else (workdir or ".")
        behaviors.append(
            _behavior(
                "directory",
                _resolve_path(target, workdir),
                "read",
                inherited_status,
                f"{cmd} directory read",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd == "stat":
        target = path_tokens[0] if path_tokens else (workdir or ".")
        behaviors.append(
            _behavior(
                "unknown",
                _resolve_path(target, workdir),
                "read",
                inherited_status,
                "stat metadata read",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd in {"cat", "head", "tail", "grep", "sed", "awk"}:
        for target in path_tokens:
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(target or ".", workdir),
                    "read",
                    inherited_status,
                    f"{cmd} file read",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd in {"rm", "unlink", "rmdir"}:
        for target in path_tokens:
            behaviors.append(
                _behavior(
                    "file" if cmd != "rmdir" else "directory",
                    _resolve_path(target, workdir),
                    "delete",
                    inherited_status,
                    f"{cmd} deletion",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd in {"touch", "mkdir", "mktemp"}:
        for target in path_tokens or ([workdir] if workdir else []):
            behaviors.append(
                _behavior(
                    "directory" if cmd == "mkdir" else "file",
                    _resolve_path(target or ".", workdir),
                    "create",
                    inherited_status,
                    f"{cmd} creation",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd in {"chmod", "chown"}:
        for target in path_tokens:
            behaviors.append(
                _behavior(
                    "unknown",
                    _resolve_path(target, workdir),
                    "setattr",
                    inherited_status,
                    f"{cmd} metadata change",
                    original_command,
                )
            )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd == "cp" and len(path_tokens) >= 2:
        for source in path_tokens[:-1]:
            behaviors.append(
                _behavior(
                    "file",
                    _resolve_path(source, workdir),
                    "read",
                    inherited_status,
                    "cp source read",
                    original_command,
                )
            )
        behaviors.append(
            _behavior(
                "file",
                _resolve_path(path_tokens[-1], workdir),
                "write",
                inherited_status,
                "cp destination write",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd == "mv" and len(path_tokens) >= 2:
        behaviors.append(
            _behavior(
                "file",
                _resolve_path(path_tokens[0], workdir),
                "delete",
                inherited_status,
                "mv source removal",
                original_command,
            )
        )
        behaviors.append(
            _behavior(
                "file",
                _resolve_path(path_tokens[-1], workdir),
                "create",
                inherited_status,
                "mv destination creation",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if cmd in {"python", "python3", "node", "ruby", "perl"} and path_tokens:
        behaviors.append(
            _behavior(
                "process",
                cmd,
                "execute",
                "partial",
                f"{cmd} interpreter execution",
                original_command,
            )
        )
        behaviors.append(
            _behavior(
                "file",
                _resolve_path(path_tokens[0], workdir),
                "read",
                "partial",
                f"{cmd} script input",
                original_command,
            )
        )
        return ShellAnalysis(original_command, behaviors, "partial", notes)

    if cmd in {"echo", "printf", "true", "false", "test"}:
        return ShellAnalysis(original_command, behaviors, inherited_status, notes)

    if path_tokens:
        target = path_tokens[0]
        behaviors.append(
            _behavior(
                "unknown",
                _resolve_path(target, workdir),
                "unknown",
                "unresolved",
                f"unsupported shell command: {cmd}",
                original_command,
            )
        )
    else:
        behaviors.append(
            _behavior(
                "process",
                cmd,
                "execute",
                "partial",
                f"unsupported process command: {cmd}",
                original_command,
            )
        )
    return ShellAnalysis(original_command, behaviors, "unresolved", notes)


def analyze_shell_command(command: str, workdir: Optional[str] = None) -> ShellAnalysis:
    """Conservatively map one shell command into resource capability events.

    The analyzer is intentionally not a full shell interpreter. It extracts
    stable resource evidence when possible, and marks pipelines, redirection,
    nested shell and variable expansion with partial/unresolved confidence.
    """

    command = str(command or "").strip()
    if not command:
        return ShellAnalysis(command, [], "unresolved", ["empty shell command"])

    tokens = _tokenize(command)
    if not tokens:
        return ShellAnalysis(command, [], "unresolved", ["empty shell command"])

    notes: List[str] = []
    inherited_status: InferenceStatus = "resolved"
    if any(token in SHELL_OPERATORS for token in tokens):
        inherited_status = "partial"
        notes.append("shell command chaining or pipeline")
    if any(token in REDIRECT_READ or token in REDIRECT_WRITE for token in tokens):
        inherited_status = _merge_status(inherited_status, "partial")
        notes.append("shell redirection")
    if re.search(r"`[^`]+`|\$\([^)]*\)|\$\{[^}]+\}|\$[A-Za-z_][A-Za-z0-9_]*", command):
        inherited_status = "unresolved"
        notes.append("shell variable or command expansion")

    behaviors: List[ShellBehavior] = []
    for segment in _split_segments(tokens):
        analysis = _analyze_segment(
            segment,
            workdir=workdir,
            original_command=command,
            inherited_status=inherited_status,
        )
        behaviors.extend(analysis.behaviors)
        notes.extend(analysis.notes)

    if not behaviors:
        overall_status: InferenceStatus = "unresolved"
    else:
        overall_status = _merge_status(
            inherited_status,
            *(behavior.inference_status for behavior in behaviors),
        )

    return ShellAnalysis(
        command=command,
        behaviors=behaviors,
        overall_status=overall_status,
        notes=sorted(set(notes)),
    )
