# CopilotAlias

Read one simple Claude Code agent `.md` file and print a preview with supported
Copilot CLI model names, without changing the original file.

This is a **preview tool**, not an agent runner or a full migration tool.
VS Code mode keeps supported native Claude aliases; it is not a general Copilot
model display-name translator.

## Start here

- [Skill ZIP](prepare-claude-agent.zip)
- [ZIP SHA256 checksum](prepare-claude-agent.zip.sha256)
- [Payload file hashes](payload-manifest.sha256)
- [Detailed Windows guide](prepare-claude-agent/README.md)

The checksum checks integrity, not publisher identity. Compare the ZIP hash
against an expected value from a **separately trusted source**, not just its sidecar.

## Live model selection

Every CLI preview queries the authenticated Copilot catalog through the approved
local runtime. Only models whose catalog policy is `enabled` are eligible.

| Input | Selection |
| --- | --- |
| Family alias, such as `sonnet` | Latest available standard numeric version in that family |
| Explicit version, such as `claude-sonnet-5-5` | Same version if available; dotted/hyphenated numeric spellings are equivalent |
| Unavailable numeric version | Closest available version in the same family: prefer the same major, then nearest major/minor, with newer versions breaking ties |

A version substitution is reported on stderr with the requested and selected
models. Exact special catalog IDs may pass unchanged, but context, date, provider
and variant suffixes are never stripped to find a substitute. Discovery errors,
unknown policy, missing families and ambiguous matches reject. There is no static
fallback, saved catalog or Claude-environment lookup.

The helper starts a metadata-only Copilot runtime in a temporary directory, with
bounded discovery and cleanup. It creates no agent session, sends no inference
prompt and does not give the runtime the input file or preview. CLI mode needs
approved network access and existing Copilot authentication; VS Code mode stays
offline. The [Windows guide](prepare-claude-agent/README.md) covers prerequisites.

## Windows quickstart

**First complete steps 1–4 of the [Windows guide](prepare-claude-agent/README.md).**
You need IT-approved, patched Python **3.12.x**, approved **PyYAML 6.x** and
**github-copilot-sdk 1.0.28** already provisioned, plus an approved, authenticated
Copilot CLI executable. Verify the trusted checksum, then extract into a fresh, private,
nonsynced local NTFS directory using the approved extraction/MOTW process.
A drive letter alone does not establish those storage requirements.

Replace the absolute paths below with your approved interpreter and extracted
skill folder. This uses a bundled example; do not copy or overwrite it.

```powershell
$Python = 'C:\Approved Runtime\python.exe'
$Copilot = 'C:\Approved Copilot\copilot.exe'
$SkillRoot = 'C:\Approved Private\Claude Preparation\prepare-claude-agent'
$Converter = Join-Path -Path "$SkillRoot" -ChildPath 'scripts\prepare_agent.py' -ErrorAction Stop
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' "$Converter" 'sonnet-alias.md' '--target' 'cli' '--copilot-path' "$Copilot"
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 0) { throw 'Preview failed or did not start; inspect stderr and stop' }
```

The exit-code reset affects only current-process bookkeeping, not machine policy.
If execution or dependencies are blocked, **stop and contact IT**. Do not change
security settings or bypass restrictions. Keep previews on the console; do not
redirect them into agent files. Follow the guide for other inputs and refusals.

## Use in Copilot

Only with approval, follow the guide to install a **pristine fresh copy from the
verified ZIP** into `<repo>\.github\skills\prepare-claude-agent`.
Never install by copying a working folder containing staged private inputs.
In the approved Copilot CLI session, explicitly request the skill:

```text
/skills reload
/prepare-claude-agent Preview source basename sonnet-alias.md, target cli, approved Python C:\Approved Runtime\python.exe, approved Copilot C:\Approved Copilot\copilot.exe. Preview only; do not launch or publish an agent.
```

For VS Code, use the approved workspace and skill discovery, then explicitly
request `/prepare-claude-agent` with basename `sonnet-alias.md`, target `vscode`
and the approved Python path. Native Claude mode supports only `sonnet`, `opus`,
`haiku` and `inherit`; no automatic trust or settings changes are performed.

Direct Python CLI previews perform authenticated catalog discovery without
uploading the source. Invoking the skill inside Copilot is separate cloud
processing: get data approval before an agent reads inputs or previews. **Never commit
staged inputs.** `.gitignore` and private folders do not prevent agent access or
cloud disclosure; follow IT retention rules.

## What is supported

Only `name`, `description`, `model` and `tools: []` are supported today.
The first three must be nonempty strings. Hooks, skills, effort, turn limits,
unknown fields and nonempty tools **reject**; they are not silently dropped.
Use UTF-8 without BOM. Invalid UTF-8 and disallowed controls reject; accepted
UTF-8 body bytes are preserved exactly. Native VS Code names use this tool's
conservative lowercase-letter/hyphen rule: `[a-z]+(?:-[a-z]+)*`.
This is not a complete VS Code runtime validator.

## Validation and limits

The test suites exercise conversion, input guards, catalog discovery failures,
model selection and packaging with synthetic catalogs. They do not depend on
network access or today's model availability. The finite
[model inventory](prepare-claude-agent/tests/model_cases.json) retains historical
source references as test data, not a production catalog or freshness check.
See the [skill tests](prepare-claude-agent/tests), [builder tests](tests/test_build_package.py)
and maintainer commands below. Expected rejections are not successful translations.

Separately, 16 historical Windows PowerShell 5.1 checks exercised the guide's
exit-code pattern with stand-in programs, not this Python tool. Those checks are
not included in this repository.

Native Windows Python, WDAC/AppLocker/CLM behavior and live Copilot/VS Code skill
loading or model execution are **not verified**. Empty-tool and model-policy
enforcement are not proven by a preview. This is not a Windows or live-agent
certification.

## Maintainers

Runtime dependency pins are in [requirements.txt](prepare-claude-agent/requirements.txt);
[requirements-test.txt](prepare-claude-agent/requirements-test.txt) references them for tests.
Managed Windows hosts must continue using an already-approved runtime as
explained in the [Windows guide](prepare-claude-agent/README.md).

Run from the repository root:

```sh
python3 -I -B -X utf8 -m unittest discover -s tests -v
python3 -I -B -X utf8 -m unittest discover -s prepare-claude-agent/tests -v
python3 build_package.py   # rebuilds prepare-claude-agent.zip and sha256 manifests
```

Rebuild only when the packaged payload changes. Rebuilding changes the ZIP and
checksum files; commit `prepare-claude-agent.zip`,
`prepare-claude-agent.zip.sha256` and `payload-manifest.sha256` together.

## License

[MIT](LICENSE) — Copyright (c) 2026 Nadav Ben Haim.
