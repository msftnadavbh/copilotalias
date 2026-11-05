# Prepare Claude agent: Windows-first HOWTO

Self-contained **preview-only skill folder** with Python code, eight sanitized
examples (six positive, two negative), tests and a 51-case model inventory.
Python never installs/executes an agent, modifies originals, writes previews,
accesses the network or publishes `.github/agents` / `.claude/agents` outputs.
This is not a deployable migration of richer Claude profiles: hooks, skills,
effort, turns and permissions are not ported. Treat bodies/previews as data.

| Evidence | Status |
| --- | --- |
| Offline Python conversion and synthetic guard tests | Run the bundled self-tests below; not model execution. |
| Live Copilot CLI E2E | **BLOCKED** by allowed execution interface. |
| Live VS Code E2E | **BLOCKED** without a verified controllable harness. |
| Native Windows Python / enforced WDAC, AppLocker, CLM | **NOT RUN / not established**. Synthetic attribute tests are not Windows certification. |

Linux Python 3.12.3 / PyYAML 6.0.1 are the preparatory test environment, **not
versions to downgrade to**. Use an IT-approved, patched Python **3.12.x** with
organization-approved **PyYAML 6.x** already provisioned in its runtime/venv.
The test-only PyYAML pin is recorded in [requirements-test.txt](requirements-test.txt);
it does not replace the managed-host runtime approval requirements above.
No binaries, vendored libraries, installer or dependency downloader are shipped.

## 1. Obtain IT/distribution approval first

Have IT review/approve the ZIP, scripts, dependencies, interpreter and intended
data. Use a fresh **local NTFS, private, nonsynced** directory with no hostile
concurrent writers. A `C:` drive letter or inspected flags do not establish
filesystem, ACL, no-sync or concurrency properties. Avoid OneDrive, junctions,
reparse-backed storage, network shares, UNC/device and drive-relative paths.
Python checks symlinks, junctions and exposed reparse flags root-to-leaf with
`lstat`. Non-symlink reparse behavior and placeholder hydration vary; the code
cannot guarantee detection of all cloud placeholders before I/O. **Nonsynced
local storage is a required control**, not something inferred from these checks.
Sources must be regular files with exactly one hard link; a bounded read of at
most 1 MiB + 1 byte rejects oversize/growing inputs. Checked paths can still race
before open: this is **not a race-free sandbox**; private storage without hostile
concurrent writers is mandatory throughout verification, extraction and copying.

If Python/PyYAML or execution is not approved/available, **stop and contact IT**.
Python is not a workaround for WDAC/AppLocker, Mark-of-the-Web, Constrained
Language Mode or script blocking. Do not relax execution policy, clear MOTW or
use Unblock-File, disable AV, elevate, use EncodedCommand/Invoke-Expression,
change global settings, or download/install dependencies. Follow approval,
signing and allowlisting requirements; this package claims no code signing.

## 2. Verify ZIP integrity against a separately trusted hash

Use the release hash supplied through an independently trusted/approved channel,
not merely a sidecar delivered with an untrusted ZIP. `.sha256` files detect
byte changes; they do **not** authenticate a publisher or grant approval.
Example paths below are placeholders; replace with approved absolute local paths.
Run the PowerShell blocks in order in the same approved session. If any command
is blocked by policy, stop; do not seek an alternate bypass.
Use the approved **console workflow** without changing existing host preferences
to make tests pass. If native-stderr handling in ISE, remoting or automation
interrupts self-tests or expected-rejection checks, stop and contact IT.

```powershell
$Archive = 'C:\Approved Intake\prepare-claude-agent.zip'
$ExpectedSHA256 = 'REPLACE_WITH_SEPARATELY_TRUSTED_64_HEX_SHA256'
if ($ExpectedSHA256 -notmatch '\A[0-9A-Fa-f]{64}\z') { throw 'Provide a separately trusted 64-hex ZIP hash' }
$ActualSHA256 = (Get-FileHash -LiteralPath "$Archive" -Algorithm SHA256 -ErrorAction Stop).Hash
if ($ActualSHA256 -ine $ExpectedSHA256) { throw 'ZIP integrity mismatch; stop' }
```

## 3. Extract into a fresh destination (never overwrite)

Use this `Expand-Archive` example **only where IT approves the extraction method
and MOTW handling**. Do not assume it preserves zone tags, or use extraction to
discard them or bypass security controls. If the handling is not approved, stop IT.

```powershell
$Extraction = 'C:\Approved Private\Claude Preparation'
if (Test-Path -LiteralPath "$Extraction" -ErrorAction Stop) { throw 'Extraction destination already exists; choose a fresh approved location' }
Expand-Archive -LiteralPath "$Archive" -DestinationPath "$Extraction" -ErrorAction Stop
$SkillRoot = Join-Path -Path "$Extraction" -ChildPath 'prepare-claude-agent' -ErrorAction Stop
$Converter = Join-Path -Path "$SkillRoot" -ChildPath 'scripts\prepare_agent.py' -ErrorAction Stop
```

The ZIP has a single `prepare-claude-agent/` root and exactly 15 payload files.
Keep the **entire folder** together, including root `SKILL.md`, this HOWTO,
`scripts`, `fixtures` and `tests`. No Force/overwrite extraction. Stop for any
unexpected payload. The external payload manifest records every payload hash.

## 4. Check the approved interpreter/dependency and run self-tests

Use the explicit, IT-approved absolute Python executable (including an approved
venv's executable if applicable), not PATH lookup or an arbitrary launcher.
`-I` ignores user-site, PYTHONPATH and all PYTHON environment variables, while
allowing approved runtime/venv site-packages. `-B` separately disables bytecode
caches; environment cache settings alone are ignored by `-I`. `-X utf8` avoids
default-encoding ambiguity. Isolation is **not** an OS security sandbox.

Immediately before each native executable call, reset
`$global:LASTEXITCODE = $null`; immediately afterward reject null or any code
other than the exact expected value. This resets only exit-code bookkeeping in
the current PowerShell process, **not machine policy or host preferences**.
Global-qualified resets and reads avoid local shadowing and stale success/failure
codes after startup failure. These examples still require the approved console
workflow; native PowerShell protocol validation is not established by Linux tests.

```powershell
$Python = 'C:\Approved Runtime\python.exe'
if ($Python -notmatch '\A[A-Za-z]:[\\/]' -or $SkillRoot -notmatch '\A[A-Za-z]:[\\/]') { throw 'Require approved absolute local paths' }
if (-not (Test-Path -LiteralPath "$Python" -PathType Leaf -ErrorAction Stop)) { throw 'Approved interpreter unavailable; contact IT' }
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' '-c' "import sys,yaml; print(sys.version); print('PyYAML',yaml.__version__); assert sys.version_info[:2] == (3,12); assert yaml.__version__.split('.')[0] == '6'"
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 0) { throw 'Runtime/dependency check failed or did not start; stop and contact IT' }
$Tests = Join-Path -Path "$SkillRoot" -ChildPath 'tests' -ErrorAction Stop
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' '-m' 'unittest' 'discover' '-s' "$Tests" '-v'
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 0) { throw 'Self-tests failed or did not start; stop' }
```

Tests keep scratch data under the skill folder and clean it. They run actual
converter subprocesses with **their own explicit** `-I -B -X utf8` flags (parent
flags are not inherited). Link tests can skip only when OS privileges/filesystem
prevent link creation; inspect skips rather than claiming native Windows proof.
Synthetic Windows reparse/location tests exercise logic, not the Windows kernel
or enterprise policy. Do not change machine policy/privileges to make tests pass.

## 5. Preview examples; optionally stage one authorized input

Validate the **entire** chosen basename before constructing any shell command:
`^[A-Za-z0-9][A-Za-z0-9_.-]*\.md$`, no newline, and no Windows reserved device
stem (`CON`, `PRN`, `AUX`, `NUL`, `COM1`..`COM9`, `LPT1`..`LPT9`, any case or
extra extension). The PowerShell equivalent below uses absolute regex anchors.
Use separate quoted arguments/call operator or an argv vector; never evaluate a
command string. Targets are **literal** `cli` / `vscode`, not arbitrary text.

```powershell
$Fixture = 'sonnet-alias.md'
if ($Fixture -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9_.-]*\.md\z' -or $Fixture -match '\A(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw 'Unsafe basename' }
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' "$Converter" "$Fixture" '--target' 'cli'
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 0) { throw 'CLI preview failed or did not start; inspect stderr and stop' }
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' "$Converter" "$Fixture" '--target' 'vscode'
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 0) { throw 'Native VS Code preview failed or did not start; inspect stderr and stop' }
```

Stdout is the preview, stderr diagnostics; successful conversion returns 0 and
converter validation failure returns 1 with empty stdout (argument-usage errors
return 2). **Accepted UTF-8 body bytes are preserved exactly**, including TAB,
CRLF and no final newline; only CLI headers are reserialized. Before any stdout
write, both targets strictly decode the final preview as UTF-8 and reject C0
codepoints 0..31 except TAB/LF/CR (9/10/13), and DEL/C1 codepoints 127..159.
Invalid UTF-8/binary or disallowed controls reject with fixed safe diagnostics,
whether output is captured or a TTY. No stripping or escaping of body bytes,
raw-output bypass or alternative output mode. This is a narrow control policy, **not universal
Unicode anti-spoofing or content safety**. Sources are never rewritten. **Do not pipe or
redirect previews into agent files**: Windows PowerShell 5.1 `>` / Out-File can
reencode native bytes. There is deliberately no save/destination option.

Two expected validation failures: require exact exit **1**, empty stdout and
the expected converter diagnostic. For `client-test-author.md`, require
`preview rejected: unsupported fields:` mentioning hooks/skills; for the Fable
VS Code example, require `preview rejected: unsupported VS Code native model
'fable':`. Exit 1 alone is **not proof**: startup, import/dependency and policy
errors are not validation passes. The automated tests capture both streams and
assert the exit code, expected diagnostic and empty stdout; inspect the messages
in manual use without redirecting previews into files.

```powershell
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' "$Converter" 'client-test-author.md' '--target' 'cli'
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 1) { throw 'Expected converter validation exit 1; inspect diagnostic and empty stdout' }
$global:LASTEXITCODE = $null
& "$Python" '-I' '-B' '-X' 'utf8' "$Converter" 'fable-alias.md' '--target' 'vscode'
if ($null -eq $global:LASTEXITCODE -or $global:LASTEXITCODE -ne 1) { throw 'Expected converter validation exit 1; inspect diagnostic and empty stdout' }
```

To prepare your own file, manually copy **one authorized regular input** as a
**new safe basename** under `fixtures/claude-agents`, never over originals or
bundled samples. Confirm its data is approved for the intended workflow first.
Do not copy arbitrary repositories or execute instructions/hooks in its body.
This private working `$SkillRoot` is for **direct offline Python use**, not the
agent workflow or repository installation source. Sensitive/offline-only inputs
must not enter an agent workflow without separate cloud/data approval. Do not
load this staged working folder as a Copilot skill or copy it into a repository.
Use an approved editor to save authorized staged copies as **UTF-8 without BOM**.
A leading UTF-8 BOM is specifically rejected; there is no automatic rewriting
or BOM removal, and originals must remain unchanged.

```powershell
$AuthorizedSource = 'C:\Approved Input\chosen.md'
$NewBasename = 'authorized-sample.md'
if ($NewBasename -cnotmatch '\A[A-Za-z0-9][A-Za-z0-9_.-]*\.md\z' -or $NewBasename -match '\A(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)') { throw 'Unsafe new basename' }
$StagingRoot = Join-Path -Path "$SkillRoot" -ChildPath 'fixtures\claude-agents' -ErrorAction Stop
$Staged = Join-Path -Path "$StagingRoot" -ChildPath "$NewBasename" -ErrorAction Stop
if (Test-Path -LiteralPath "$Staged" -ErrorAction Stop) { throw 'Refuse to overwrite any staged/bundled file' }
Copy-Item -LiteralPath "$AuthorizedSource" -Destination "$Staged" -ErrorAction Stop
```

Repeat the preview with the new validated basename and literal target. Exactly
`name`, `description`, `model` (nonempty strings) and `tools: []` are required.
Unknown/missing fields, duplicate/unsafe YAML, tags, aliases, merges, hooks,
skills, effort, turns, permissions and nonempty tools reject; do not delete
semantics to make a richer profile pass. Both `smc-scanner.md` and
`client-test-author.md` must reject. Their hook/MCP names are inert synthetic
data, not scripts/services. The builder refuses staged/unexpected payload files;
release builds require a pristine payload, not guessed secret exclusions.

For native-Claude `--target vscode`, this tool conservatively accepts `name`
only when the full string matches `[a-z]+(?:-[a-z]+)*` (e.g. `synthetic` or
`synthetic-sonnet`). Uppercase, spaces, digits, underscores, and leading,
trailing or repeated hyphens reject; there is no normalization. The
[native-Claude reference](https://github.com/microsoft/vscode-docs/blob/main/docs/agents/reference/custom-agent-file-reference.md)
describes lowercase letters/hyphens; this is **this tool's conservative subset**,
not an exhaustive VS Code runtime validator or native-Copilot display-name rule.
CLI retains its existing nonempty-string name behavior, subject to the final
preview UTF-8/control policy above.

## 6. Only with approval, install a fresh pristine copy into an approved repository

This is optional and is **not performed by the converter**. Use an existing,
approved repository skill parent; if it is missing, ask the repository owner.
Refuse an existing destination; do not merge/overwrite. **Never copy the working
`$SkillRoot` or previously staged data.** Reverify the ZIP against the separately
trusted `$ExpectedSHA256`, then extract into a **new, never-used, approved**
`$InstallExtraction`, distinct from the working extraction. Absence alone does
not prove a path has never been used: select it under the IT process. Apply the
same local/private/no-hostile-concurrency prerequisites and IT-approved
extraction/MOTW handling from steps 1 and 3. Do not stage anything in this fresh
extraction. Copy only its pristine `$InstallSource` folder, with all resources,
not just `SKILL.md` (a file-only skill-add operation may omit resources).

```powershell
if ($ExpectedSHA256 -notmatch '\A[0-9A-Fa-f]{64}\z') { throw 'Require the separately trusted 64-hex ZIP hash' }
$InstallArchiveSHA256 = (Get-FileHash -LiteralPath "$Archive" -Algorithm SHA256 -ErrorAction Stop).Hash
if ($InstallArchiveSHA256 -ine $ExpectedSHA256) { throw 'ZIP integrity mismatch; do not install' }
$InstallExtraction = 'C:\Approved Private\Claude Pristine Install' # new, never-used approved path, not $Extraction
if (Test-Path -LiteralPath "$InstallExtraction" -ErrorAction Stop) { throw 'Choose a new, never-used approved install extraction' }
Expand-Archive -LiteralPath "$Archive" -DestinationPath "$InstallExtraction" -ErrorAction Stop
$InstallSource = Join-Path -Path "$InstallExtraction" -ChildPath 'prepare-claude-agent' -ErrorAction Stop
$SkillParent = 'C:\Approved Repo\.github\skills'
$InstalledSkill = Join-Path -Path "$SkillParent" -ChildPath 'prepare-claude-agent' -ErrorAction Stop
if (-not (Test-Path -LiteralPath "$SkillParent" -PathType Container -ErrorAction Stop)) { throw 'Ask repo owner to approve/provide skill parent' }
if (Test-Path -LiteralPath "$InstalledSkill" -ErrorAction Stop) { throw 'Refuse existing skill destination' }
Copy-Item -LiteralPath "$InstallSource" -Destination "$InstalledSkill" -Recurse -ErrorAction Stop
```

## 7. Explicit skill invocation (separate service/data approval)

Offline Python preparation does not upload a staged source. **Copilot invocation
is separate cloud processing** via your organization's configured service; loaded
skill resources, source content or previews may enter Copilot context. Require
approved data handling and service/workspace permissions before proceeding.
Any inputs later staged inside the repository skill are **working-tree data**
and may enter Copilot context. Never commit staged inputs; handle them under
retention/IT processes. `.gitignore`, private folders and "never commit" do
**not** prevent agent access or cloud disclosure. Keep sensitive/offline-only
inputs in the direct-Python working folder unless separately approved for the
agent/cloud workflow; do not expose that working folder to the agent.

In an already approved Copilot CLI session for that repository:

```text
/skills reload
/skills list
/skills info prepare-claude-agent
/prepare-claude-agent Preview source basename sonnet-alias.md, target cli, approved Python C:\Approved Runtime\python.exe. Preview only; do not launch or publish an agent.
```

For VS Code, use the approved workspace and installed Copilot skill discovery
under enterprise policy. Do not bypass Workspace Trust or enable prohibited
features. Confirm this skill is discovered, then explicitly prompt:

```text
/prepare-claude-agent Preview source basename sonnet-alias.md, target vscode, approved Python C:\Approved Runtime\python.exe. Preview only; do not launch or publish an agent.
```

Root `SKILL.md` sets `disable-model-invocation: true` for manual invocation; no
automatic dispatch or permission grants are configured. Actual skill discovery,
flag enforcement, target parsing and target model/tool behavior are unverified.

## 8. Troubleshooting and removal

* Import/runtime/policy failure: stop IT; do not remove isolation flags, add
  PYTHONPATH, fetch dependencies, unblock files or change security policy.
* Path/reparse/hardlink refusal: ask IT for compliant private local NTFS storage
  and a fresh authorized regular copy; do not use network/UNC runtime workarounds.
* Oversize: 1 MiB is the input cap, enforced with a bounded read, not only stat
  size. No truncation. Unsupported header/model: refuse, never silently normalize.
* UTF-8/BOM/control/name refusal: use an approved editor on an authorized staged
  copy, not the original. No automatic encoding, BOM, control or name rewriting.
* Skill missing: verify the entire folder, resource location and enterprise
  policy; do not globally install or bypass trust. No output is a deployed agent.

For removal, the repository owner/IT must inspect reparse points, staged data
and retention requirements, then remove **only the verified copied skill
folder**, never `.github/skills`, `.github`, the repository or global
directories. This guide provides no automated deletion routine. Then reload
skills in the approved application. No parent/global removal.

## Model selection compatibility snapshot: 2026-11-04

The finite [inventory](tests/model_cases.json) contains 51 unique documented
selectors/IDs/representative provider forms, each tested for both targets:
**CLI 22 mapped / 29 expected rejections; native VS Code 4 passthrough / 47
expected rejections**. Rejection passes are not successful translations. This
is not Anthropic's internal test suite, all arbitrary/retired model names or live
inference. General Code selectors are tested for portability, not asserted valid
in every subagent header. Source URLs, categories, overlaps and as-of metadata
are preserved in the inventory; tests do not generate expectations from code.

| CLI input | Candidate |
| --- | --- |
| `sonnet`, `claude-sonnet-5-5`, `claude-sonnet-5.5` | `claude-sonnet-5.5` |
| `opus`, `claude-opus-5-5`, `claude-opus-5.5` | `claude-opus-5.5` |
| `haiku`, `claude-haiku-5-5`, `claude-haiku-5.5` | `claude-haiku-5.5` |
| `fable`, `claude-fable-5-1`, `claude-fable-5.1` | `claude-fable-5.1` |
| `claude-sonnet-5`, `claude-fable-5`, `claude-opus-5` | Same exact ID |
| `claude-opus-4-8`, `claude-opus-4.8` | `claude-opus-4.8` |
| `claude-sonnet-4-6`, `claude-sonnet-4.6` | `claude-sonnet-4.6` |
| `claude-haiku-4-5`, `claude-haiku-4.5` | `claude-haiku-4.5` |
| `claude-opus-4.8-fast` | Same exact Copilot ID; no hyphenated API fast spelling |

These are project pins, **not** Claude account/environment/provider/parent-state
emulation. Fable's pin 5.1 differs from Claude apps gateway 5.0. Native VS Code
preserves only `sonnet`, `opus`, `haiku`, `inherit` unchanged, not `.agent.md`
display-name translation; inherit preserves intent, not original parent identity
or CLI pin equivalence. CLI rejects inherit; VS Code rejects Fable/explicit IDs.
Dynamic `default`/`best`/`opusplan`, every `[1m]` selector, dated IDs, unsupported
versions and provider-specific spellings (Bedrock `anthropic.` prefixes, Vertex
`@date`, ARNs, custom deployment/gateway names) reject. Never strip suffixes even
when redundant in Claude. IDs copied from a provider but spelled exactly like
an allowlisted API ID follow that ID's CLI mapping: provider origin/configuration
is neither detected nor reproduced. Native VS Code still rejects explicit IDs.

Advertised catalog: lead-reported CLI 1.0.105 completion snapshot from
`copilot --no-auto-update completion bash`, 2026-11-04: **not** account
availability, parser, dispatch, context-window or enforcement evidence.
`model-policy: required`, `strict-tools-list: true`, `tools: []` remain unverified
intent. No target isolation field. Lead-reported installed Claude 2.1.284 is older
than Haiku 5.5's documented minimum 2.1.293; no Claude update or actual run here.

## Official references

* [GitHub: adding CLI skills and relative resources](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills)
* [VS Code skills/manual invocation](https://code.visualstudio.com/docs/copilot/customization/agent-skills)
* [Python command-line isolation and flags](https://docs.python.org/3.12/using/cmdline.html), [stat attributes](https://docs.python.org/3.12/library/stat.html), [lstat](https://docs.python.org/3.12/library/os.html#os.lstat)
* [PowerShell Get-FileHash](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-filehash?view=powershell-5.1), [Expand-Archive](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.archive/expand-archive?view=powershell-5.1), [call operator](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_operators?view=powershell-5.1), [LASTEXITCODE](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_automatic_variables?view=powershell-5.1)
* [Application control and PowerShell](https://learn.microsoft.com/en-us/powershell/scripting/security/app-control/how-app-control-works?view=powershell-7.5) (policy behavior is version/environment dependent, not tested here)
* Model-selection/API/catalog/provider/VS Code model URLs are embedded in the unchanged [source-backed inventory](tests/model_cases.json).
