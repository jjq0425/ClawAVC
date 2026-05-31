"""Process & security context collector for the ClawAVC monitor.

Goal: identify the **OpenClaw agent main process** (the watched target —
NOT the ClawAVC backend itself) and snapshot its security context plus any
tool-calling subprocesses spawned under it. Each round records who's actually
running the agent and what SELinux/AppArmor label any tool subprocess inherits.

Discovery strategy (in order, each falls through on failure):

    0. cached_main:     if caller passed a recent (pid, starttime_ticks) tuple
                        and that PID still exists with the same starttime,
                        reuse it. Avoids scanning /proc on every round.

    1. cmdline match:   scan all /proc/*/cmdline (and comm) lowercased for any
                        `hint_keyword` (default: 'openclaw'). Exclude any
                        process matching `exclude_keywords` (default: 'clawavc',
                        'claw-avc', 'claw_avc') OR the calling process itself.

    2. cwd boost:       among cmdline candidates, prefer those whose cwd is
                        at-or-below `openclaw_root` (when provided).

    3. Tie-break:       by earliest starttime (oldest = most likely the parent
                        agent rather than a transient subprocess).

    4. fd-writer:       last resort — find a process holding the session JSONL
                        currently open. Only works if writer doesn't close-and-
                        reopen on each line, which most loggers do.

Per-process info (collect_pid_info / collect_pid_slim):

    identity      pid, ppid, tgid, comm, cmdline, argv, exe, cwd, root
    credentials   uid+name, gid+name, loginuid, audit_session_id
    resources     state, threads, vm_*_kb, num_fds, /proc/<pid>/io
    capabilities  Inh/Prm/Eff/Bnd/Amb decoded to names + raw hex
    sandbox       seccomp mode, no_new_privs
    MAC labels    SELinux/AppArmor: /proc/<pid>/attr/{current,exec,prev,
                  fscreate,keycreate,sockcreate}
    isolation     namespaces (each ns inode), cgroups, container detection
    env           whitelisted only (PATH/USER/HOME/LANG/CONTAINER ...)
    start time    clock_ticks → epoch → ISO

Per-round bundle (collect_for_round):

    main          full info on the OpenClaw main process
    ancestors     parent chain of the main (4 levels by default)
    descendants   ALL live subprocess descendants of the main process
                  (slim entries — keeps cmdline + exe + uid +
                  security_labels.current). Captures tool subprocesses.
    fallback_writers  if discovery fell through to fd-writer, those PIDs
    discovery     {method, matched_keyword, candidates, selected_pid}
    system        SELinux mode + policyvers + mls, AppArmor enabled,
                  kernel, hostname (deliberately NOT clawavc_self_label —
                  we report only the watched target's labels)
"""

from __future__ import annotations

import json
import os
import pwd
import grp
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

PROC = Path("/proc")
SELF_PID = os.getpid()

# Default keywords that identify an OpenClaw process from its cmdline/comm.
DEFAULT_HINT_KEYWORDS: Tuple[str, ...] = ("openclaw",)
# Keywords that explicitly mean "NOT OpenClaw" (the AVC backend, monitor, etc.).
DEFAULT_EXCLUDE_KEYWORDS: Tuple[str, ...] = ("clawavc", "claw-avc", "claw_avc")

# These comm values are never OpenClaw — they're shells, multiplexers, init,
# auth wrappers, etc. Used to drop obvious false positives like
# `tmux new -s openclaw` (whose cwd may even be /root/.openclaw).
DEFAULT_COMM_BLACKLIST: Tuple[str, ...] = (
    "bash", "sh", "zsh", "fish", "dash", "ksh", "csh", "tcsh", "ash",
    "tmux", "tmux: server", "tmux: client", "screen", "dtach", "byobu",
    "sudo", "su", "doas", "systemd", "init", "login", "sshd", "agetty",
)

# Capability names by bit position (kernel/include/uapi/linux/capability.h).
CAP_NAMES: List[str] = [
    "CAP_CHOWN", "CAP_DAC_OVERRIDE", "CAP_DAC_READ_SEARCH", "CAP_FOWNER",
    "CAP_FSETID", "CAP_KILL", "CAP_SETGID", "CAP_SETUID",
    "CAP_SETPCAP", "CAP_LINUX_IMMUTABLE", "CAP_NET_BIND_SERVICE", "CAP_NET_BROADCAST",
    "CAP_NET_ADMIN", "CAP_NET_RAW", "CAP_IPC_LOCK", "CAP_IPC_OWNER",
    "CAP_SYS_MODULE", "CAP_SYS_RAWIO", "CAP_SYS_CHROOT", "CAP_SYS_PTRACE",
    "CAP_SYS_PACCT", "CAP_SYS_ADMIN", "CAP_SYS_BOOT", "CAP_SYS_NICE",
    "CAP_SYS_RESOURCE", "CAP_SYS_TIME", "CAP_SYS_TTY_CONFIG", "CAP_MKNOD",
    "CAP_LEASE", "CAP_AUDIT_WRITE", "CAP_AUDIT_CONTROL", "CAP_SETFCAP",
    "CAP_MAC_OVERRIDE", "CAP_MAC_ADMIN", "CAP_SYSLOG", "CAP_WAKE_ALARM",
    "CAP_BLOCK_SUSPEND", "CAP_AUDIT_READ", "CAP_PERFMON", "CAP_BPF",
    "CAP_CHECKPOINT_RESTORE",
]

SECCOMP_MODES = {"0": "disabled", "1": "strict", "2": "filter"}

ENV_WHITELIST = {
    "PATH", "USER", "LOGNAME", "HOME", "PWD", "SHELL", "TERM", "LANG", "LC_ALL",
    "container", "CONTAINER", "KUBERNETES_SERVICE_HOST", "DOCKER_CONTAINER",
    "VIRTUAL_ENV", "PYTHONPATH", "NODE_ENV",
}

try:
    _CLK_TCK = os.sysconf("SC_CLK_TCK") or 100
except Exception:
    _CLK_TCK = 100

try:
    with open("/proc/stat") as f:
        _BTIME = next(int(line.split()[1]) for line in f if line.startswith("btime "))
except Exception:
    _BTIME = 0


# ─── Low-level safe readers ────────────────────────────────────────────────

def _safe_read_text(path, max_bytes: int = 65536) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return f.read(max_bytes).decode(errors="replace")
    except Exception:
        return None


def _safe_readlink(path) -> Optional[str]:
    try:
        return os.readlink(str(path))
    except Exception:
        return None


def _parse_kb(s: Optional[str]) -> Optional[int]:
    if not s:
        return None
    try:
        return int(s.strip().split()[0])
    except Exception:
        return None


def _try_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(str(v).strip().split()[0])
    except Exception:
        return None


def _read_status_kv(pid_dir: Path) -> Dict[str, str]:
    text = _safe_read_text(pid_dir / "status") or ""
    out: Dict[str, str] = {}
    for line in text.splitlines():
        k, _, v = line.partition(":")
        if k:
            out[k.strip()] = v.strip()
    return out


def _read_attr_dir(pid_dir: Path) -> Dict[str, str]:
    """Read /proc/<pid>/attr/{current,exec,prev,fscreate,keycreate,sockcreate}.
    Covers both SELinux and AppArmor labels."""
    out: Dict[str, str] = {}
    for name in ("current", "exec", "prev", "fscreate", "keycreate", "sockcreate"):
        v = _safe_read_text(pid_dir / "attr" / name)
        if v:
            v = v.strip().rstrip("\x00")
            if v:
                out[name] = v
    return out


def _read_starttime_ticks(pid_dir: Path) -> Optional[int]:
    """Parse /proc/<pid>/stat field 22 (starttime in clock ticks since boot)."""
    text = _safe_read_text(pid_dir / "stat") or ""
    if not text:
        return None
    rp = text.rfind(")")
    if rp < 0:
        return None
    fields = text[rp + 2:].split()
    if len(fields) <= 19:
        return None
    try:
        return int(fields[19])
    except ValueError:
        return None


def _starttime_dict(pid_dir: Path) -> Optional[Dict[str, Any]]:
    ticks = _read_starttime_ticks(pid_dir)
    if ticks is None:
        return None
    if not _BTIME or not _CLK_TCK:
        return {"clock_ticks": ticks}
    epoch = _BTIME + ticks / _CLK_TCK
    iso = datetime.fromtimestamp(epoch, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    return {"clock_ticks": ticks, "epoch": epoch, "iso": iso}


def _read_cmdline(pid_dir: Path) -> Tuple[List[str], Optional[str]]:
    raw = b""
    try:
        with open(pid_dir / "cmdline", "rb") as f:
            raw = f.read(65536)
    except Exception:
        pass
    if not raw:
        return [], None
    argv = [s.decode(errors="replace") for s in raw.split(b"\x00") if s]
    return argv, " ".join(argv) if argv else None


def _read_comm(pid_dir: Path) -> Optional[str]:
    return (_safe_read_text(pid_dir / "comm") or "").strip() or None


def _decode_caps(hexstr: Optional[str]) -> List[str]:
    if not hexstr:
        return []
    try:
        mask = int(hexstr, 16)
    except Exception:
        return []
    out = []
    for i, name in enumerate(CAP_NAMES):
        if mask & (1 << i):
            out.append(name)
    extra = mask >> len(CAP_NAMES)
    if extra:
        out.append(f"<unknown_bits:0x{extra:x}>")
    return out


def _detect_container(cgroup_lines: List[str], root_link: Optional[str]) -> Optional[str]:
    blob = "\n".join(cgroup_lines).lower()
    if "kubepods" in blob:
        return "kubernetes"
    if "/docker/" in blob or "/docker-" in blob or "docker.scope" in blob:
        return "docker"
    if "podman" in blob:
        return "podman"
    if "crio-" in blob or "/cri-" in blob:
        return "cri-o"
    if "containerd" in blob:
        return "containerd"
    if "lxc" in blob:
        return "lxc"
    if root_link and root_link not in ("/", ""):
        return "chroot_or_unknown_container"
    return None


def _uid_to_name(uid: int) -> Optional[str]:
    try:
        return pwd.getpwuid(uid).pw_name
    except Exception:
        return None


def _gid_to_name(gid: int) -> Optional[str]:
    try:
        return grp.getgrgid(gid).gr_name
    except Exception:
        return None


def _parse_id_quartet(line: Optional[str], name_resolver=None) -> Optional[Dict[str, Any]]:
    if not line:
        return None
    parts = line.split()
    if len(parts) < 4:
        return None
    try:
        real, eff, saved, fs = (int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return None
    out: Dict[str, Any] = {"real": real, "effective": eff, "saved": saved, "fs": fs}
    if name_resolver:
        out["real_name"] = name_resolver(real)
        out["effective_name"] = name_resolver(eff)
    return out


# ─── Full per-PID collector ────────────────────────────────────────────────

def collect_pid_info(pid: int, with_fd_sample: bool = True, fd_sample_limit: int = 20) -> Dict[str, Any]:
    pid_dir = PROC / str(pid)
    if not pid_dir.is_dir():
        return {"pid": pid, "alive": False}

    info: Dict[str, Any] = {"pid": pid, "alive": True}
    argv, cmdline = _read_cmdline(pid_dir)
    info["argv"] = argv
    info["cmdline"] = cmdline
    info["comm"] = _read_comm(pid_dir)
    info["exe"] = _safe_readlink(pid_dir / "exe")
    info["cwd"] = _safe_readlink(pid_dir / "cwd")
    info["root"] = _safe_readlink(pid_dir / "root")

    status = _read_status_kv(pid_dir)
    info["state"] = status.get("State")
    info["ppid"] = _try_int(status.get("PPid"))
    info["tgid"] = _try_int(status.get("Tgid"))
    info["threads"] = _try_int(status.get("Threads"))
    info["uid"] = _parse_id_quartet(status.get("Uid"), name_resolver=_uid_to_name)
    info["gid"] = _parse_id_quartet(status.get("Gid"), name_resolver=_gid_to_name)
    info["groups"] = (status.get("Groups") or "").split() or None
    info["vm_rss_kb"] = _parse_kb(status.get("VmRSS"))
    info["vm_size_kb"] = _parse_kb(status.get("VmSize"))
    info["vm_peak_kb"] = _parse_kb(status.get("VmPeak"))
    info["vm_swap_kb"] = _parse_kb(status.get("VmSwap"))

    info["capabilities"] = {
        "inheritable": _decode_caps(status.get("CapInh")),
        "permitted":   _decode_caps(status.get("CapPrm")),
        "effective":   _decode_caps(status.get("CapEff")),
        "bounding":    _decode_caps(status.get("CapBnd")),
        "ambient":     _decode_caps(status.get("CapAmb")),
        "raw": {
            "inh": status.get("CapInh"), "prm": status.get("CapPrm"),
            "eff": status.get("CapEff"), "bnd": status.get("CapBnd"),
            "amb": status.get("CapAmb"),
        },
    }

    info["seccomp"] = SECCOMP_MODES.get(status.get("Seccomp", ""), status.get("Seccomp"))
    info["no_new_privs"] = (status.get("NoNewPrivs") == "1") if status.get("NoNewPrivs") else None

    info["security_labels"] = _read_attr_dir(pid_dir) or None

    info["loginuid"] = _try_int(_safe_read_text(pid_dir / "loginuid"))
    info["audit_session_id"] = _try_int(_safe_read_text(pid_dir / "sessionid"))

    cgroup_text = _safe_read_text(pid_dir / "cgroup") or ""
    cgroup_lines = [ln.strip() for ln in cgroup_text.splitlines() if ln.strip()]
    info["cgroups"] = cgroup_lines
    info["container"] = _detect_container(cgroup_lines, info["root"])

    ns_dir = pid_dir / "ns"
    namespaces: Dict[str, str] = {}
    if ns_dir.exists():
        try:
            for entry in ns_dir.iterdir():
                link = _safe_readlink(entry)
                if link:
                    namespaces[entry.name] = link
        except Exception:
            pass
    info["namespaces"] = namespaces or None

    fd_dir = pid_dir / "fd"
    num_fds: Optional[int] = None
    fd_sample: List[Dict[str, str]] = []
    if fd_dir.exists():
        try:
            entries = sorted(fd_dir.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 1 << 30)
            num_fds = len(entries)
            if with_fd_sample:
                for entry in entries[:fd_sample_limit]:
                    target = _safe_readlink(entry)
                    if target is not None:
                        fd_sample.append({"fd": entry.name, "target": target})
        except Exception:
            pass
    info["fds"] = {"num_fds": num_fds, "sample": fd_sample}

    io_text = _safe_read_text(pid_dir / "io") or ""
    io_dict: Dict[str, int] = {}
    for line in io_text.splitlines():
        k, _, v = line.partition(":")
        if k:
            try:
                io_dict[k.strip()] = int(v.strip())
            except ValueError:
                pass
    info["io"] = io_dict or None

    env_raw = _safe_read_text(pid_dir / "environ", max_bytes=131072) or ""
    env_dict: Dict[str, str] = {}
    for chunk in env_raw.split("\x00"):
        if not chunk or "=" not in chunk:
            continue
        k, _, v = chunk.partition("=")
        if k in ENV_WHITELIST:
            env_dict[k] = v
    info["env"] = env_dict or None

    info["start_time"] = _starttime_dict(pid_dir)
    return info


# ─── Slim per-PID collector — for descendants list ─────────────────────────

def collect_pid_slim(pid: int, depth: Optional[int] = None) -> Dict[str, Any]:
    """Slim entry for tool-subprocess descendants. Keeps cmdline + exe + uid +
    SELinux current label — the things you actually want to inspect when
    figuring out 'which tool process ran under what label'."""
    pid_dir = PROC / str(pid)
    if not pid_dir.is_dir():
        return {"pid": pid, "alive": False}
    argv, cmdline = _read_cmdline(pid_dir)
    status = _read_status_kv(pid_dir)
    uid_quartet = _parse_id_quartet(status.get("Uid"), name_resolver=_uid_to_name)
    out: Dict[str, Any] = {
        "pid": pid,
        "ppid": _try_int(status.get("PPid")),
        "comm": _read_comm(pid_dir),
        "cmdline": (cmdline[:512] if cmdline else None),
        "exe": _safe_readlink(pid_dir / "exe"),
        "user": (uid_quartet or {}).get("effective_name"),
        "uid": (uid_quartet or {}).get("effective"),
        "security_labels": _read_attr_dir(pid_dir) or None,
        "state": status.get("State"),
    }
    if depth is not None:
        out["depth"] = depth
    return out


# ─── Discovery: find OpenClaw main process ─────────────────────────────────

def _list_pids() -> List[int]:
    try:
        return sorted(int(p.name) for p in PROC.iterdir() if p.name.isdigit())
    except Exception:
        return []


def _validate_cached(cached: Optional[Tuple[int, int]]) -> Optional[int]:
    """Returns cached pid if it still exists with the same starttime, else None."""
    if not cached:
        return None
    pid, ticks_known = cached
    pid_dir = PROC / str(pid)
    if not pid_dir.is_dir():
        return None
    ticks_now = _read_starttime_ticks(pid_dir)
    if ticks_now is None or ticks_now != ticks_known:
        return None
    return pid


def _path_under(child: Optional[str], parent: str) -> bool:
    if not child or not parent:
        return False
    try:
        c = os.path.realpath(child)
        p = os.path.realpath(parent)
    except Exception:
        return False
    if c == p:
        return True
    return c.startswith(p.rstrip("/") + "/")


def _cmdline_match_score(argv: List[str], comm: Optional[str], hints: Iterable[str]) -> int:
    """Score how strongly a process's cmdline/comm matches the OpenClaw hints.
    Returns 0 if no match. Higher is more confident.

    Matching is anchored — we don't accept any random argv string that happens
    to contain 'openclaw' (which would falsely match e.g. a test command whose
    `-c` body imports `openclaw_main_pid`). Acceptable matches:
        100 — argv[0] basename equals a hint exactly                    (`openclaw`)
         95 — argv[0] basename starts with `<hint>-` or `<hint>_`       (`openclaw-gateway`)
         80 — hint substring of argv[0] basename                        (`my-openclawd`)
         70 — hint substring of comm                                    (`openclaw-gatewa`)
         60 — hint substring of any *path component* in argv[1:]        (`/opt/openclaw/main.js`)
    """
    if not argv and not comm:
        return 0
    prog_low = (os.path.basename(argv[0]) if argv else "").lower()
    comm_low = (comm or "").lower()
    score = 0
    hints_low = [h.lower() for h in hints if h]

    for h in hints_low:
        if prog_low == h:
            return 100
        if prog_low.startswith(h + "-") or prog_low.startswith(h + "_"):
            score = max(score, 95)
        if h in prog_low:
            score = max(score, 80)
        if h in comm_low:
            score = max(score, 70)

    # Path-component match in any non-flag argv element.
    for arg in argv[1:]:
        if "/" not in arg:
            continue
        for component in arg.lower().split("/"):
            if any(h in component for h in hints_low):
                score = max(score, 60)
                break
    return score


def find_openclaw_main_pid(
    openclaw_root: str = "",
    hint_keywords: Iterable[str] = DEFAULT_HINT_KEYWORDS,
    exclude_keywords: Iterable[str] = DEFAULT_EXCLUDE_KEYWORDS,
    comm_blacklist: Iterable[str] = DEFAULT_COMM_BLACKLIST,
    self_pid_exclude: int = SELF_PID,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """Locate the OpenClaw main process via cmdline/comm matching with a
    cwd boost when openclaw_root is provided.

    Returns (pid_or_None, debug_info_dict). The debug dict carries
    {method, candidates_count, candidates[:8], selected_pid, selected_score,
    selected_reason} — useful for explaining decisions in tests/logs."""
    hints = tuple(k for k in hint_keywords if k)
    excludes_low = tuple(k.lower() for k in exclude_keywords if k)
    blacklist = {b.strip() for b in comm_blacklist if b}

    candidates: List[Dict[str, Any]] = []
    for pid in _list_pids():
        if pid == self_pid_exclude or pid <= 1:
            continue
        pid_dir = PROC / str(pid)
        try:
            argv, cmdline = _read_cmdline(pid_dir)
            comm = _read_comm(pid_dir) or ""
        except Exception:
            continue

        # Drop shells / multiplexers / init / auth wrappers outright.
        if comm.strip() in blacklist:
            continue

        score = _cmdline_match_score(argv, comm, hints)
        if score == 0:
            continue

        searchable_low = ((cmdline or "") + " " + comm).lower()
        if any(x in searchable_low for x in excludes_low):
            continue

        cwd = _safe_readlink(pid_dir / "cwd")
        cwd_under_root = bool(openclaw_root) and _path_under(cwd, openclaw_root)
        if cwd_under_root:
            score += 20

        starttime = _read_starttime_ticks(pid_dir)
        candidates.append({
            "pid": pid,
            "comm": comm,
            "cmdline": cmdline,
            "cwd": cwd,
            "starttime": starttime if starttime is not None else 1 << 60,
            "score": score,
            "cwd_under_root": cwd_under_root,
        })

    debug: Dict[str, Any] = {"candidates_count": len(candidates),
                             "candidates": candidates[:8]}

    if not candidates:
        debug["method"] = "no_match"
        return None, debug

    # Highest score wins; ties broken by earliest starttime (parent-most).
    candidates.sort(key=lambda c: (-c["score"], c["starttime"]))
    chosen = candidates[0]
    debug["method"] = "cmdline_match"
    debug["selected_pid"] = chosen["pid"]
    debug["selected_score"] = chosen["score"]
    debug["selected_reason"] = (
        "cwd_boost" if chosen["cwd_under_root"]
        else f"score={chosen['score']}"
    )
    return chosen["pid"], debug


# ─── Process tree walking ──────────────────────────────────────────────────

def _build_pid_tree() -> Dict[int, List[int]]:
    """Build ppid → children index in one /proc pass."""
    tree: Dict[int, List[int]] = {}
    for pid in _list_pids():
        status = _read_status_kv(PROC / str(pid))
        ppid = _try_int(status.get("PPid"))
        if ppid is None:
            continue
        tree.setdefault(ppid, []).append(pid)
    return tree


def find_descendants(
    root_pid: int,
    max_depth: int = 6,
    max_count: int = 64,
) -> List[Dict[str, Any]]:
    """BFS down the process tree from root_pid. Returns a list of slim dicts
    (each with security_labels.current). Excludes root_pid itself."""
    tree = _build_pid_tree()
    out: List[Dict[str, Any]] = []
    queue: List[Tuple[int, int]] = [(root_pid, 0)]
    seen = {root_pid}
    while queue and len(out) < max_count:
        p, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        for child in tree.get(p, []):
            if child in seen:
                continue
            seen.add(child)
            slim = collect_pid_slim(child, depth=depth + 1)
            out.append(slim)
            if len(out) >= max_count:
                break
            queue.append((child, depth + 1))
    return out


def collect_ancestors(pid: int, max_depth: int = 4) -> List[Dict[str, Any]]:
    """Walk parent chain (immediate parent first)."""
    out: List[Dict[str, Any]] = []
    seen = set()
    cur = pid
    for _ in range(max_depth):
        if cur <= 1 or cur in seen:
            break
        seen.add(cur)
        status = _read_status_kv(PROC / str(cur))
        ppid = _try_int(status.get("PPid"))
        if ppid is None or ppid == cur or ppid <= 1:
            break
        cur = ppid
        if not (PROC / str(cur)).is_dir():
            break
        out.append(collect_pid_slim(cur))
    return out


# ─── fd-writer fallback (kept for completeness) ────────────────────────────

def find_pids_writing(file_path: str, exclude_self: bool = True) -> List[int]:
    """Walk /proc/<pid>/fd looking for symlinks pointing to file_path.
    Note: most line-buffered loggers close the fd between writes, so this
    fallback rarely succeeds. Kept as a last-resort hint."""
    try:
        target = os.path.realpath(file_path)
    except Exception:
        return []
    results: List[int] = []
    for pid in _list_pids():
        if exclude_self and pid == SELF_PID:
            continue
        fd_dir = PROC / str(pid) / "fd"
        try:
            entries = list(fd_dir.iterdir())
        except (FileNotFoundError, PermissionError, OSError):
            continue
        for entry in entries:
            link = _safe_readlink(entry)
            if not link:
                continue
            try:
                if os.path.realpath(link) == target:
                    results.append(pid)
                    break
            except Exception:
                continue
    return results


# ─── System-level security context ─────────────────────────────────────────

def collect_system_context() -> Dict[str, Any]:
    """System-wide security/kernel context. Deliberately does NOT include
    the caller's own SELinux label — we want to characterise the watched
    target, not the AVC backend itself."""
    out: Dict[str, Any] = {
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "hostname": socket.gethostname(),
    }
    enforce = _safe_read_text("/sys/fs/selinux/enforce")
    if enforce is not None:
        out["selinux"] = {
            "mode": {"0": "permissive", "1": "enforcing"}.get(enforce.strip(), "unknown"),
            "policyvers": (_safe_read_text("/sys/fs/selinux/policyvers") or "").strip() or None,
            "mls": (_safe_read_text("/sys/fs/selinux/mls") or "").strip() or None,
        }
    else:
        out["selinux"] = {"mode": "disabled"}
    aa = _safe_read_text("/sys/module/apparmor/parameters/enabled")
    out["apparmor"] = {"enabled": (aa.strip() == "Y") if aa else False}
    out["kernel"] = (_safe_read_text("/proc/version") or "").strip() or None
    return out


# ─── Top-level entry ───────────────────────────────────────────────────────

def collect_for_round(
    openclaw_root: str = "",
    jsonl_path: str = "",
    hint_keywords: Optional[Iterable[str]] = None,
    exclude_keywords: Optional[Iterable[str]] = None,
    cached_main: Optional[Tuple[int, int]] = None,
    ancestors: int = 4,
    descendants_depth: int = 6,
    descendants_max: int = 64,
) -> Dict[str, Any]:
    """Locate OpenClaw main process and collect a full snapshot for one round.
    Always returns a dict (never raises). On failure carries an 'error' field.

    Args:
        openclaw_root:    OpenClaw install dir, used as a cwd hint when
                          disambiguating cmdline-matched candidates.
        jsonl_path:       Session JSONL path — only used as a fd-writer
                          fallback if cmdline matching fails.
        hint_keywords:    Cmdline/comm keywords to match (case-insensitive).
                          Default: ('openclaw',).
        exclude_keywords: Keywords that disqualify a candidate. Default:
                          ('clawavc', 'claw-avc', 'claw_avc').
        cached_main:      (pid, starttime_ticks) tuple. If still alive with
                          same starttime, reused without rescanning /proc.
    """
    started = time.time()
    out: Dict[str, Any] = {
        "openclaw_root": openclaw_root,
        "jsonl_path": jsonl_path,
        "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }

    hk = tuple(hint_keywords) if hint_keywords else DEFAULT_HINT_KEYWORDS
    xk = tuple(exclude_keywords) if exclude_keywords else DEFAULT_EXCLUDE_KEYWORDS

    main_pid: Optional[int] = None
    discovery: Dict[str, Any] = {}

    # Strategy 0: cached
    cached_pid = _validate_cached(cached_main)
    if cached_pid:
        main_pid = cached_pid
        discovery = {"method": "cached", "selected_pid": cached_pid}
    else:
        # Strategy 1+2: cmdline + cwd
        main_pid, discovery = find_openclaw_main_pid(
            openclaw_root=openclaw_root, hint_keywords=hk, exclude_keywords=xk,
        )

    # Strategy 4: fd-writer fallback (rarely works for buffered loggers)
    fallback_writers: List[int] = []
    if main_pid is None and jsonl_path:
        fallback_writers = find_pids_writing(jsonl_path)
        if fallback_writers:
            main_pid = fallback_writers[0]
            discovery = {"method": "fd_writer_fallback", "selected_pid": main_pid,
                         "writers": fallback_writers}

    out["discovery"] = discovery
    if fallback_writers:
        out["fallback_writers"] = fallback_writers

    out["system"] = collect_system_context()

    if main_pid is None:
        out["error"] = (
            f"OpenClaw main process not found "
            f"(searched cmdline keywords={list(hk)}, fd-writer={bool(jsonl_path)})"
        )
        out["collect_duration_ms"] = int((time.time() - started) * 1000)
        return out

    # Collect main + ancestors + descendants
    try:
        out["main"] = collect_pid_info(main_pid, with_fd_sample=True)
    except Exception as e:
        out["main"] = {"pid": main_pid, "error": str(e)}

    try:
        out["ancestors"] = collect_ancestors(main_pid, max_depth=ancestors)
    except Exception as e:
        out["ancestors"] = []
        out["ancestors_error"] = str(e)

    try:
        out["descendants"] = find_descendants(
            main_pid, max_depth=descendants_depth, max_count=descendants_max,
        )
    except Exception as e:
        out["descendants"] = []
        out["descendants_error"] = str(e)

    # Surface key labels at top level for quick consumption
    main_labels = (out.get("main") or {}).get("security_labels") or {}
    out["main_selinux_label"] = main_labels.get("current")
    out["main_exec_label"] = main_labels.get("exec")
    descendant_labels = []
    for d in out.get("descendants") or []:
        lbl = (d.get("security_labels") or {}).get("current")
        if lbl:
            descendant_labels.append({
                "pid": d.get("pid"), "comm": d.get("comm"),
                "cmdline": d.get("cmdline"), "label": lbl,
            })
    out["tool_subprocess_labels"] = descendant_labels

    out["collect_duration_ms"] = int((time.time() - started) * 1000)
    return out


# Backwards-compat alias used by old code paths.
def collect_for_session(jsonl_path: str, ancestors: int = 4) -> Dict[str, Any]:
    """DEPRECATED. Use collect_for_round(openclaw_root, jsonl_path, ...) instead.
    This thin wrapper retains the old signature for callers that haven't been
    migrated; behaviour falls straight through to collect_for_round."""
    return collect_for_round(jsonl_path=jsonl_path, ancestors=ancestors)


# ─── Standalone test ───────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Locate OpenClaw main + collect security snapshot")
    parser.add_argument("--openclaw-root", default="", help="OpenClaw install dir (cwd hint)")
    parser.add_argument("--jsonl", default="", help="Session JSONL path (fd-writer fallback only)")
    parser.add_argument("--hint", action="append", help="Extra hint keyword (repeatable)")
    parser.add_argument("--ancestors", type=int, default=4)
    parser.add_argument("--descendants-depth", type=int, default=6)
    parser.add_argument("--descendants-max", type=int, default=64)
    args = parser.parse_args()
    hk = (list(DEFAULT_HINT_KEYWORDS) + (args.hint or [])) or None
    print(json.dumps(
        collect_for_round(
            openclaw_root=args.openclaw_root,
            jsonl_path=args.jsonl,
            hint_keywords=hk,
            ancestors=args.ancestors,
            descendants_depth=args.descendants_depth,
            descendants_max=args.descendants_max,
        ),
        ensure_ascii=False, indent=2, default=str,
    ))
