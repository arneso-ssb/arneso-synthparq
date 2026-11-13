"""Build and exercise an isolated wheel installation outside the checkout.

Requires uv on PATH. Dependency installation uses the local uv cache only.
Run after ``uv sync --locked`` so dependencies/build requirements are cached.
"""

import os
import subprocess
import sys
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory


def main() -> None:
    """Verify installability and the full CLI workflow with no source imports."""
    root = Path(__file__).resolve().parents[1]
    scratch = Path("/tmp/opencode") if Path("/tmp/opencode").is_dir() else None
    with TemporaryDirectory(prefix="synthparq-wheel-", dir=scratch) as temporary:
        work = Path(temporary)
        environment = {**os.environ, "UV_OFFLINE": "1"}
        environment.pop("PYTHONPATH", None)

        def run(*args: str) -> subprocess.CompletedProcess[str]:
            try:
                return subprocess.run(
                    args,
                    cwd=work,
                    env=environment,
                    check=True,
                    text=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as exc:
                print(exc.stdout, file=sys.stderr)
                print(exc.stderr, file=sys.stderr)
                raise

        run(
            "uv",
            "build",
            "--project",
            str(root),
            "--wheel",
            "--out-dir",
            str(work / "dist"),
        )
        wheel = next((work / "dist").glob("*.whl"))
        with zipfile.ZipFile(wheel) as archive:
            files = archive.namelist()
            assert any(name.endswith("/licenses/LICENSE") for name in files)
            assert not any(name.endswith(".parquet") for name in files)
            assert not any("timeseriestest" in name for name in files)
        run("uv", "venv", "--python", sys.executable, str(work / "env"))
        binaries = work / "env" / ("Scripts" if os.name == "nt" else "bin")
        python = binaries / ("python.exe" if os.name == "nt" else "python")
        cli = binaries / ("synthparq.exe" if os.name == "nt" else "synthparq")
        requirements = work / "runtime.txt"
        run(
            "uv",
            "export",
            "--project",
            str(root),
            "--locked",
            "--no-dev",
            "--no-emit-project",
            "--output-file",
            str(requirements),
        )
        environment["UV_PROJECT_ENVIRONMENT"] = str(work / "env")
        run(
            "uv",
            "sync",
            "--project",
            str(root),
            "--locked",
            "--no-dev",
            "--no-install-project",
            "--python",
            str(python),
        )
        run("uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel))
        run(str(cli), "--help")
        run(str(cli), "--version")
        run(
            str(cli),
            "profile",
            str(root / "examples/source.parquet"),
            "--init-config",
            str(work / "export.json"),
        )
        profile = work / "profile.json"
        run(
            str(cli),
            "profile",
            str(root / "examples/source.parquet"),
            "--config",
            str(root / "examples/export.json"),
            "--out",
            str(profile),
        )
        output = work / "synthetic.parquet"
        result = run(
            str(cli), "generate", str(profile), "--out", str(output), "--seed", "42"
        )
        print(result.stdout.strip())
        run(
            str(python),
            "-c",
            "import synthparq, pyarrow.parquet as pq; from pathlib import Path; "
            f"assert not Path(synthparq.__file__).is_relative_to({str(root)!r}); "
            "assert pq.read_table('synthetic.parquet').num_rows == 48",
        )
        print("PASS: isolated wheel installation and offline CLI workflow")


if __name__ == "__main__":
    main()
