"""Build only the pristine, explicitly listed payload; Python 3.12 stdlib only."""

import hashlib
import io
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys
import zipfile


ROOT = Path(__file__).absolute().parent
PAYLOAD_PATHS = (
    "README.md",
    "SKILL.md",
    "requirements-test.txt",
    "fixtures/claude-agents/client-test-author.md",
    "fixtures/claude-agents/fable-alias.md",
    "fixtures/claude-agents/haiku-alias.md",
    "fixtures/claude-agents/opus-alias.md",
    "fixtures/claude-agents/opus-pinned.md",
    "fixtures/claude-agents/smc-scanner.md",
    "fixtures/claude-agents/sonnet-alias.md",
    "fixtures/claude-agents/sonnet-pinned.md",
    "scripts/prepare_agent.py",
    "tests/model_cases.json",
    "tests/test_prepare_agent.py",
)


def check_component(name):
    if (name in (".", "..") or name.rstrip(" .") != name
            or any(char in name for char in '\\/:<>"|?*')
            or re.match(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.IGNORECASE)):
        raise ValueError(f"unsafe or Windows-reserved component: {name!r}")


def check_entry(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or path.as_posix() != name:
        raise ValueError(f"unsafe archive entry: {name!r}")
    for component in path.parts:
        check_component(component)


def checked_stat(path):
    location = str(path)
    windows = PureWindowsPath(location)
    if (not path.is_absolute() or location.startswith(("\\", "//"))
            or (windows.drive and (not re.fullmatch(r"[A-Za-z]:", windows.drive) or not windows.root))):
        raise ValueError("builder requires absolute local paths, not UNC/device/drive-relative locations")
    for component in (*reversed(path.parents), path):
        if component.name:
            check_component(component.name)
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("builder rejects symlinks/reparse points")
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("builder ancestors must be directories")
    return info


def collect_payload(payload):
    expected_dirs = {"."}
    for name in PAYLOAD_PATHS:
        check_entry(name)
        expected_dirs.update(str(parent) for parent in PurePosixPath(name).parents)
    found = {}
    seen = set()
    pending = [payload]
    while pending:
        path = pending.pop()
        info = checked_stat(path)
        name = path.relative_to(payload).as_posix()
        if name != ".":
            check_entry(name)
        folded = name.casefold()
        if folded in seen:
            raise ValueError(f"Windows name collision: {name!r}")
        seen.add(folded)
        if stat.S_ISDIR(info.st_mode):
            if name not in expected_dirs:
                raise ValueError(f"unexpected payload directory: {name!r}")
            pending.extend(sorted(path.iterdir()))
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            if name not in PAYLOAD_PATHS:
                raise ValueError(f"unexpected payload file: {name!r}")
            found[name] = path
        else:
            raise ValueError(f"payload must contain regular single-link files: {name!r}")
    if found.keys() != set(PAYLOAD_PATHS):
        raise ValueError("missing payload files")
    # shortcut: checked reads/writes can race; use private nonsynced local storage without hostile concurrent writers.
    return {name: found[name].read_bytes() for name in sorted(found)}


def build(root=ROOT):
    contents = collect_payload(root / "prepare-claude-agent")
    archive_path = root / "prepare-claude-agent.zip"
    outputs = (archive_path, root / "prepare-claude-agent.zip.sha256", root / "payload-manifest.sha256")
    for path in outputs:
        checked_stat(path.parent)
        try:
            info = checked_stat(path)
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("owned output must be a regular single-link file")
    memory = io.BytesIO()
    names = ["prepare-claude-agent/" + name for name in contents]
    with zipfile.ZipFile(memory, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in contents.items():
            entry = zipfile.ZipInfo("prepare-claude-agent/" + name, date_time=(2020, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | 0o644) << 16
            entry.compress_type = zipfile.ZIP_STORED
            archive.writestr(entry, data)
    archive_bytes = memory.getvalue()
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as check:
        assert check.namelist() == names
        assert all(check.read("prepare-claude-agent/" + name) == data for name, data in contents.items())
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  prepare-claude-agent/{name}\n"
        for name, data in contents.items()
    ).encode("utf-8")
    digest = hashlib.sha256(archive_bytes).hexdigest()
    archive_path.write_bytes(archive_bytes)
    outputs[1].write_bytes(f"{digest}  prepare-claude-agent.zip\n".encode("ascii"))
    outputs[2].write_bytes(manifest)
    return digest


if __name__ == "__main__":
    try:
        print(build())
    except (OSError, ValueError) as error:
        print(f"build rejected: {error}", file=sys.stderr)
        sys.exit(1)
