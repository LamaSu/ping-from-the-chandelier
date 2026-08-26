"""Run the SIA CLI on Windows without symlink privilege.

`workspace.create_run_dir()` builds each run directory by symlinking every
file from the version dir (sia_cli/workspace.py:604). On Windows,
`os.symlink` needs SeCreateSymbolicLinkPrivilege — Developer Mode or an
elevated shell — so without it every `sia evals run` and every `sia
improve` dies with:

    OSError: [WinError 1314] A required privilege is not held by the client

There is no fallback in 0.1.4. This shim gives it one: try the real
symlink, and on OSError copy instead. A copied run dir behaves the same
for reading; the only thing lost is that edits inside `.sia/runs/` no
longer write through to the version dir, which the harness does not do.

    python harness/sia_win.py evals run --no-harbor
    python harness/sia_win.py improve --max-cost 3.00
"""
import os
import pathlib
import shutil
import subprocess
import sys

_real_symlink = os.symlink


def _symlink_or_copy(src, dst, target_is_directory=False, **kwargs):
    try:
        return _real_symlink(src, dst, target_is_directory, **kwargs)
    except OSError:
        pass
    # `src` is written relative to the link's own directory by the caller.
    source = pathlib.Path(src)
    if not source.is_absolute():
        source = pathlib.Path(dst).parent / source
    dest = pathlib.Path(dst)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest, ignore_errors=True)
        else:
            dest.unlink(missing_ok=True)
    if target_is_directory or source.is_dir() or not source.exists():
        # A directory junction needs no special privilege, unlike a symlink,
        # so directories keep real link semantics — writes through the link
        # still land in the target, which `_point_version_traces_at` relies
        # on. The target may not exist yet (it links a traces dir the run has
        # not written), so create it first; `mklink` refuses a missing target.
        source.mkdir(parents=True, exist_ok=True)
        subprocess.run(["cmd", "/c", "mklink", "/J", str(dest),
                        str(source.resolve())],
                       check=True, capture_output=True)
    else:
        shutil.copy2(source.resolve(), dest)


os.symlink = _symlink_or_copy

from sia_cli.__main__ import main  # noqa: E402  (after the patch, on purpose)

if __name__ == "__main__":
    raise SystemExit(main())
