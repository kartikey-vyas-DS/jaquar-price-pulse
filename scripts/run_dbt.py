import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

from db import ROOT


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "run"
    if command not in {"run", "test", "build"}:
        raise SystemExit("Usage: python scripts/run_dbt.py [run|test|build]")

    load_dotenv(ROOT / ".env")
    env = os.environ.copy()
    dbt_exe = ROOT / ".venv" / "Scripts" / "dbt.exe"
    if not dbt_exe.exists():
        dbt_exe = Path("dbt")

    subprocess.run(
        [str(dbt_exe), command, "--profiles-dir", str(ROOT / "dbt")],
        cwd=ROOT / "dbt",
        env=env,
        check=True,
    )


if __name__ == "__main__":
    main()
