"""Command-line interface."""

from pathlib import Path

import click
import pyarrow as pa
import pyarrow.parquet as pq

from synthparq.synthetic import generate_parquet
from synthparq.synthetic import init_config
from synthparq.synthetic import profile_parquet

_FILE = click.Path(dir_okay=False, path_type=Path)
_EXISTING_FILE = click.Path(exists=True, dir_okay=False, path_type=Path)


@click.group(invoke_without_command=True)
@click.version_option(package_name="arneso-synthparq")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Create synthetic Parquet datasets from reviewed JSON profiles."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command("profile")
@click.argument("parquet_file", type=_EXISTING_FILE)
@click.option(
    "--init-config",
    "init_config_file",
    type=_FILE,
    help="Write a config template (schema only) and exit. Reads no data.",
)
@click.option(
    "--config", "config_file", type=_EXISTING_FILE, help="Export config with roles."
)
@click.option("--out", "profile_file", type=_FILE, help="Profile JSON to write.")
@click.option("--overwrite", is_flag=True, help="Replace an existing output file.")
def profile_command(
    parquet_file: Path,
    init_config_file: Path | None,
    config_file: Path | None,
    profile_file: Path | None,
    overwrite: bool,
) -> None:
    """Profile a Parquet file into a JSON file for disclosure review."""
    if init_config_file is not None and (
        profile_file is not None or config_file is not None
    ):
        raise click.UsageError(
            "--init-config cannot be combined with --out or --config."
        )
    try:
        if init_config_file is not None:
            click.echo(
                f"Wrote {init_config(parquet_file, init_config_file, overwrite=overwrite)}"
            )
            return
        if profile_file is None:
            raise click.UsageError("--out is required unless --init-config is given.")
        click.echo(
            f"Wrote {profile_parquet(parquet_file, profile_file, config_file, overwrite=overwrite)}"
        )
        click.echo(
            "Review this profile before transfer: dataset-level metadata is included."
        )
    except pa.ArrowException:
        raise click.ClickException(
            "Parquet processing failed; check file integrity and supported column types"
        ) from None
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None


@main.command("generate")
@click.argument("profile_file", type=_EXISTING_FILE)
@click.option("--out", "output_file", type=_FILE, required=True)
@click.option("--seed", type=int, default=0, show_default=True)
@click.option("--rows", "n_rows", type=click.IntRange(min=1), default=None)
@click.option("--overwrite", is_flag=True, help="Replace an existing output file.")
def generate_command(
    profile_file: Path,
    output_file: Path,
    seed: int,
    n_rows: int | None,
    overwrite: bool,
) -> None:
    """Generate synthetic Parquet data from a profile."""
    try:
        output = generate_parquet(
            profile_file, output_file, seed, n_rows, overwrite=overwrite
        )
        click.echo(f"Wrote {output} ({pq.read_metadata(output).num_rows} rows)")
    except pa.ArrowException:
        raise click.ClickException(
            "Parquet generation failed; check profile types and constraints"
        ) from None
    except (ValueError, OSError) as exc:
        raise click.ClickException(str(exc)) from None


if __name__ == "__main__":
    main(prog_name="synthparq")  # pragma: no cover
