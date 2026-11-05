"""Preview one staged Claude-format file; never install or execute an agent."""

import argparse
from pathlib import Path, PureWindowsPath
import re
import stat
import sys

import yaml
from yaml.tokens import AliasToken, AnchorToken, TagToken


ROOT = Path(__file__).absolute().parent.parent
FIXTURES = ROOT / "fixtures" / "claude-agents"
MAX_INPUT_BYTES = 1024 * 1024
CLI_MODELS = {
    "sonnet": "claude-sonnet-5.5",
    "opus": "claude-opus-5.5",
    "haiku": "claude-haiku-5.5",
    "fable": "claude-fable-5.1",
    "claude-sonnet-5-5": "claude-sonnet-5.5",
    "claude-sonnet-5": "claude-sonnet-5",
    "claude-fable-5-1": "claude-fable-5.1",
    "claude-fable-5": "claude-fable-5",
    "claude-opus-5-5": "claude-opus-5.5",
    "claude-opus-5": "claude-opus-5",
    "claude-opus-4-8": "claude-opus-4.8",
    "claude-sonnet-4-6": "claude-sonnet-4.6",
    "claude-haiku-5-5": "claude-haiku-5.5",
    "claude-haiku-4-5": "claude-haiku-4.5",
    "claude-sonnet-5.5": "claude-sonnet-5.5",
    "claude-fable-5.1": "claude-fable-5.1",
    "claude-opus-5.5": "claude-opus-5.5",
    "claude-opus-4.8": "claude-opus-4.8",
    "claude-opus-4.8-fast": "claude-opus-4.8-fast",
    "claude-sonnet-4.6": "claude-sonnet-4.6",
    "claude-haiku-5.5": "claude-haiku-5.5",
    "claude-haiku-4.5": "claude-haiku-4.5",
}


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


def preview(fixture, target):
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
    if model not in CLI_MODELS:
        raise ValueError(
            f"unsupported CLI model {model!r}: no exact CLI mapping; dynamic/context/inherit selectors "
            "and unlisted dated, provider or version IDs are not translated"
        )
    candidate = {
        "name": fields["name"],
        "description": fields["description"],
        "model": CLI_MODELS[model],
        "model-policy": "required",
        "strict-tools-list": True,
        "tools": [],
    }
    newline = b"\r\n" if lines[0] == b"---\r\n" else b"\n"
    emitted = yaml.safe_dump(candidate, sort_keys=False, allow_unicode=True).encode("utf-8")
    return checked_preview(b"---" + newline + emitted.replace(b"\n", newline) + b"---" + newline + b"".join(lines[end + 1:]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", help="basename under fixtures/claude-agents (including .md)")
    parser.add_argument("--target", required=True, choices=("cli", "vscode"))
    args = parser.parse_args()
    try:
        check_location(sys.argv[0])
        output = preview(args.fixture, args.target)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError, RecursionError) as error:
        print(f"preview rejected: {error}", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
