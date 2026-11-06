"""Preview one staged Claude-format file; never install or execute an agent."""

import argparse
from pathlib import Path, PureWindowsPath
import re
import runpy
import stat
import sys

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken


ROOT = Path(__file__).absolute().parent.parent
FIXTURES = ROOT / "fixtures" / "claude-agents"
MAX_INPUT_BYTES = 1024 * 1024
# Only plain numeric releases participate in latest/nearest selection.
MODEL_VERSION = re.compile(r"claude-([a-z]+)-([1-9][0-9]{0,2})(?:[.-](0|[1-9][0-9]{0,2}))?")


def discover_models(copilot_path):
    helper = ROOT / "scripts" / "copilot_catalog.py"
    checked_stat(helper)
    return runpy.run_path(str(helper))["discover_models"](copilot_path)


def resolve_model(model, catalog):
    """Return (catalog ID, substituted); never infer provider or variant identity."""
    if model in {"inherit", "default", "best", "opusplan", "auto"}:
        raise ValueError(f"unsupported CLI model {model!r}: no eligible CLI model; dynamic selectors are unsupported")
    requested = MODEL_VERSION.fullmatch(model)
    if not requested and model in catalog and re.fullmatch(r"claude-[a-z]+-[a-z0-9]+(?:[.-][a-z0-9]+)*", model):
        return model, False
    family = requested[1] if requested else model
    candidates = {}
    for identifier in catalog:
        parsed = MODEL_VERSION.fullmatch(identifier)
        if parsed and parsed[1] == family:
            version = (int(parsed[2]), int(parsed[3] or 0))
            if version in candidates:
                raise ValueError(f"ambiguous CLI catalog versions for {family!r}")
            candidates[version] = identifier
    if not candidates or (not requested and not re.fullmatch(r"[a-z]+", model)):
        raise ValueError(f"unsupported CLI model {model!r}: no eligible CLI model; "
                         "provider, context and variant semantics are not stripped")
    if not requested:
        return candidates[max(candidates)], False
    version = (int(requested[2]), int(requested[3] or 0))
    if version in candidates:
        return candidates[version], False
    nearest = min(candidates, key=lambda item: (
        abs(item[0] - version[0]), abs(item[1] - version[1]), -item[0], -item[1]
    ))
    return candidates[nearest], True



def check_location(location):
    windows = PureWindowsPath(location)
    if location.startswith(("\\", "//")) or (windows.drive and (
        not re.fullmatch(r"[A-Za-z]:", windows.drive) or not windows.root
    )):
        raise ValueError("UNC, device, rooted-without-drive and drive-relative locations are unsupported")


def check_component(name):
    if (name in (".", "..") or name.rstrip(" .") != name
            or any(char in name for char in '\\/:<>"|?*')
            or re.match(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", name, re.IGNORECASE)):
        raise ValueError(f"unsafe or Windows-reserved path component: {name!r}")


def reject_link(info):
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("symlink/reparse point is unsupported (including junctions and sync placeholders)")


def checked_stat(path):
    check_location(str(path))
    if not path.is_absolute():
        raise ValueError("an absolute local path is required")
    for component in (*reversed(path.parents), path):
        if component.name:
            check_component(component.name)
        info = component.lstat()
        reject_link(info)
        if component != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("source ancestors must be directories")
    return info


def read_source(source):
    info = checked_stat(source)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError("source must be a regular file with exactly one hard link")
    # shortcut: lstat/open can race; require private local nonsynced storage with no hostile concurrent writers.
    with source.open("rb") as stream:
        original = stream.read(MAX_INPUT_BYTES + 1)
    if len(original) > MAX_INPUT_BYTES:
        raise ValueError("source exceeds the 1 MiB input limit")
    return original


class StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        if not isinstance(node, yaml.MappingNode):
            raise ValueError("expected a mapping")
        result = {}
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                raise ValueError("YAML merge keys are unsupported")
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str):
                raise ValueError("field names must be strings")
            if key in result:
                raise ValueError(f"duplicate field: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def checked_preview(output):
    try:
        text = output.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("preview must be valid UTF-8") from None
    if any((ord(char) < 32 and char not in "\t\n\r") or 127 <= ord(char) <= 159 for char in text):
        raise ValueError("preview contains unsupported control characters")
    return output


def preview(fixture, target, copilot_path=None):
    check_component(fixture)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.md", fixture):
        raise ValueError("choose a fixture basename, not a path")
    original = read_source(FIXTURES / fixture)
    if original.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is unsupported; use UTF-8 without BOM")
    lines = original.splitlines(keepends=True)
    if not lines or lines[0] not in (b"---\n", b"---\r\n"):
        raise ValueError("expected opening frontmatter delimiter")
    end = next(
        (i for i in range(1, len(lines)) if lines[i] in (b"---\n", b"---\r\n", b"---")),
        None,
    )
    if end is None:
        raise ValueError("expected closing frontmatter delimiter")
    header = b"".join(lines[1:end]).decode("utf-8")
    if any(isinstance(token, (AliasToken, AnchorToken, TagToken)) for token in yaml.scan(header)):
        raise ValueError("YAML aliases, anchors and explicit tags are unsupported")
    fields = yaml.load(header, Loader=StrictLoader)
    required = {"name", "description", "model", "tools"}
    if not isinstance(fields, dict):
        raise ValueError("frontmatter must be a mapping")
    if fields.keys() != required:
        missing = sorted(required - fields.keys())
        unknown = sorted(fields.keys() - required)
        raise ValueError(f"unsupported fields: missing={missing}, unknown={unknown}")
    for key in ("name", "description", "model"):
        if not isinstance(fields[key], str) or not fields[key].strip():
            raise ValueError(f"{key} must be a nonempty string")
    if not isinstance(fields["tools"], list) or fields["tools"]:
        raise ValueError("only tools: [] is supported (intent, not enforcement)")
    model = fields["model"]
    if target == "vscode":
        if not re.fullmatch(r"[a-z]+(?:-[a-z]+)*", fields["name"]):
            raise ValueError("VS Code native name must match [a-z]+(?:-[a-z]+)*; no normalization is performed")
        if model not in ("sonnet", "opus", "haiku", "inherit"):
            raise ValueError(
                f"unsupported VS Code native model {model!r}: documented native passthrough "
                "only supports sonnet, opus, haiku, inherit; no selector, version or provider conversion"
            )
        return checked_preview(original)
    # Reject invalid output bytes before starting an authenticated metadata lookup.
    checked_preview(original)
    if not copilot_path:
        raise ValueError("CLI previews require --copilot-path with an approved absolute executable path")
    selected, substituted = resolve_model(model, discover_models(copilot_path))
    candidate = {
        "name": fields["name"],
        "description": fields["description"],
        "model": selected,
        "model-policy": "required",
        "strict-tools-list": True,
        "tools": [],
    }
    newline = b"\r\n" if lines[0] == b"---\r\n" else b"\n"
    emitted = yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True).encode("utf-8")
    output = checked_preview(b"---" + newline + emitted.replace(b"\n", newline) + b"---" + newline + b"".join(lines[end + 1:]))
    if substituted:
        print(f"model substitution: {model!r} -> {selected!r} (closest eligible version in the same family)", file=sys.stderr)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="basename under fixtures/claude-agents (including .md)")
    parser.add_argument("--target", required=True, choices=("cli", "vscode"))
    parser.add_argument("--copilot-path", help="approved absolute Copilot executable (required for cli)")
    args = parser.parse_args()
    try:
        check_location(sys.argv[0])
        output = preview(args.fixture, args.target, args.copilot_path)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RecursionError) as error:
        print(f"preview rejected: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
