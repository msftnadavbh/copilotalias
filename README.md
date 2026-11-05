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

## Four simple aliases

| Claude alias | Copilot CLI preview model |
| --- | --- |
| `sonnet` | `claude-sonnet-5.5` |
| `opus` | `claude-opus-5.5` |
| `haiku` | `claude-haiku-5.5` |
| `fable` | `claude-fable-5.1` |

These pins are project policy, not automatic matching of Claude's provider,
parent model or default selection. Other exact supported IDs are listed in the
[Windows guide](prepare-claude-agent/README.md) and [model inventory](prepare-claude-agent/tests/model_cases.json).

## Windows quickstart

**First complete steps 1–4 of the [Windows guide](prepare-claude-agent/README.md).**
You need IT-approved, patched Python **3.12.x** and approved **PyYAML 6.x** already
installed. Verify the trusted checksum, then extract into a fresh, private,
nonsynced local NTFS directory using the approved extraction/MOTW process.
A drive letter alone does not establish those storage requirements.

Replace the absolute paths below with your approved interpreter and extracted
skill folder. This uses a bundled example; do not copy or overwrite it.

```powershell
$Python = 'C:\Approved Runtime\python.exe'
$SkillRoot = 'C:\Approved Private\Claude Preparation\prepare-claude-agent'
$Converter = Join-Path -Path "$SkillRoot" -ChildPath 'scripts\prepare_agent.py' -ErrorAction Stop
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' "$Converter" 'sonnet-alias.md' '--target' 'cli'
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
/prepare-claude-agent Preview source basename sonnet-alias.md, target cli, approved Python C:\Approved Runtime\python.exe. Preview only; do not launch or publish an agent.
```

For VS Code, use the approved workspace and skill discovery, then explicitly
request `/prepare-claude-agent` with basename `sonnet-alias.md`, target `vscode`
and the approved Python path. Native Claude mode supports only `sonnet`, `opus`,
`haiku` and `inherit`; no automatic trust or settings changes are performed.

Offline Python preparation is separate from Copilot's cloud service. Get
separate data approval before an agent reads inputs or previews. **Never commit
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

This repository's **42 tests** (36 skill tests + 6 builder tests) passed on
Linux Python **3.12.3** / PyYAML **6.0.1**. Separately, **16 one-off Windows
PowerShell 5.1 checks** tested the guide's exit-code pattern using stand-in
programs, **not this Python tool**. Those checks are not included in this repository.

The finite [51-case model inventory](prepare-claude-agent/tests/model_cases.json)
is dated **2026-11-04**: CLI maps 22 and rejects 29; VS Code passes through 4 and
rejects 47. Expected rejections are not successful translations; not all models
are portable. See the [36 skill tests](prepare-claude-agent/tests/test_prepare_agent.py),
[6 builder tests](tests/test_build_package.py) and the guide's test commands.

Native Windows Python, WDAC/AppLocker/CLM behavior and live Copilot/VS Code skill
loading or model execution are **not verified**. Empty-tool and model-policy
enforcement are not proven by a preview. This is not a Windows or live-agent
certification.
