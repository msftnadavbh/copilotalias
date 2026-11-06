"""Read the authenticated Copilot catalog without creating an agent session."""

import asyncio
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile


DISCOVERY_TIMEOUT = 20
CLEANUP_TIMEOUT = 5


def _enabled_ids(models):
    if not isinstance(models, list) or not models or len(models) > 10000:
        raise ValueError("Copilot catalog is empty or malformed")
    identifiers = []
    seen = set()
    for model in models:
        identifier = getattr(model, "id", None)
        if (not isinstance(identifier, str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", identifier)
                or identifier in seen):
            raise ValueError("Copilot catalog has malformed or duplicate model IDs")
        seen.add(identifier)
        policy = getattr(model, "policy", None)
        state = getattr(policy, "state", None)
        if policy is not None and state not in ("enabled", "disabled", "unconfigured"):
            raise ValueError("Copilot catalog has an unknown model policy")
        # An advertised model without enabled policy is not proof of permission.
        if state == "enabled":
            identifiers.append(identifier)
    if not identifiers:
        raise ValueError("Copilot catalog has no policy-enabled models")
    return identifiers


async def _discover(client):
    try:
        try:
            async with asyncio.timeout(DISCOVERY_TIMEOUT):
                await client.start()
                models = await client.list_models()
        except TimeoutError:
            raise ValueError("Copilot catalog discovery timed out; retry after checking the approved runtime") from None
        except Exception:
            raise ValueError("Copilot catalog discovery failed; check runtime compatibility, authentication and connectivity") from None
        return _enabled_ids(models)
    finally:
        try:
            await asyncio.wait_for(client.stop(), timeout=CLEANUP_TIMEOUT)
        except Exception:
            try:
                await asyncio.wait_for(client.force_stop(), timeout=CLEANUP_TIMEOUT)
            except Exception:
                raise ValueError("Copilot catalog runtime cleanup failed; stop and inspect the runtime") from None


def discover_models(cli_path):
    """Return enabled IDs from a fresh approved CLI connection, never a stale cache."""
    try:
        path = Path(cli_path)
        windows = PureWindowsPath(cli_path)
        if (not path.is_absolute() or str(path).startswith(("\\", "//"))
                or (windows.drive and (not re.fullmatch(r"[A-Za-z]:", windows.drive) or not windows.root))
                or not stat.S_ISREG(path.stat().st_mode) or not os.access(path, os.X_OK)
                or (os.name == "nt" and path.suffix.lower() != ".exe")):
            raise ValueError
    except (OSError, TypeError, ValueError):
        raise ValueError("choose an approved absolute local executable Copilot path (.exe on Windows)") from None
    try:
        from copilot import CopilotClient, RuntimeConnection
    except Exception:
        raise ValueError("an approved github-copilot-sdk 1.0.28 runtime is required for CLI discovery; contact IT") from None
    try:
        with tempfile.TemporaryDirectory(prefix="copilotalias-catalog-") as directory:
            try:
                client = CopilotClient(
                    connection=RuntimeConnection.for_stdio(path=str(path), args=(
                        "--no-auto-update", "--no-custom-instructions", "--disable-builtin-mcps",
                        "--no-bash-env", "--no-remote", "--log-dir", directory,
                    )),
                    working_directory=directory,
                    log_level="none",
                    env={**os.environ, "COPILOT_GITHUB_TELEMETRY_DISABLED": "true"},
                )
            except Exception:
                raise ValueError("Copilot catalog discovery failed; check the approved SDK and runtime") from None
            return asyncio.run(_discover(client))
    except ValueError:
        raise
    except Exception:
        raise ValueError("Copilot catalog discovery failed; check the approved SDK and runtime") from None
