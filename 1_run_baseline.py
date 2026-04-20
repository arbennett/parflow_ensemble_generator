"""
Run a baseline ParFlow-CLM simulation using a runscript prepared by 0_subset_baseline.py.

Pass the same --runname, --grid, --end, and --base-dir values used during subsetting
so that the run directory and runscript path are resolved consistently.
"""

import argparse
import os

from parflow import Run
from parflow.tools.settings import set_working_directory


def parse_args():
    parser = argparse.ArgumentParser(
        description="Execute a baseline ParFlow-CLM run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Path resolution (must match 0_subset_baseline.py) ---
    parser.add_argument("--runname", default="conus2_run", help="Name of the ParFlow run")
    parser.add_argument("--grid", default="conus2", help="CONUS grid (conus1 or conus2)")
    parser.add_argument("--end", default="2005-10-03", help="Run end date (YYYY-MM-DD); used to derive water year")
    parser.add_argument("--base-dir", default="./run", help="Base directory used during subsetting")

    # --- Run overrides ---
    parser.add_argument(
        "--stop-time",
        type=float,
        default=None,
        help="Override TimingInfo.StopTime (hours). Omit to use the value from the runscript.",
    )
    parser.add_argument(
        "--met-file-name",
        default="CW3E",
        help="CLM MetFileName (root name of climate forcing files)",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    os.environ.setdefault("PARFLOW_DIR", "/usr/local/")

    # --- Resolve paths (mirrors 0_subset_baseline.py) ---
    water_year = args.end[:4]
    run_tag = f"{args.runname}_{args.grid}_{water_year}WY"
    base_dir = os.path.abspath(args.base_dir)
    pf_out_dir = os.path.join(base_dir, "outputs", run_tag)
    forcing_dir = os.path.join(base_dir, "inputs", run_tag, "forcing")
    runscript_path = os.path.join(pf_out_dir, f"{args.runname}.yaml")

    if not os.path.isfile(runscript_path):
        raise FileNotFoundError(
            f"Runscript not found: {runscript_path}\n"
            "Run 0_subset_baseline.py first, or check --runname / --base-dir."
        )

    # --- Set working directory and load run ---
    set_working_directory(pf_out_dir)
    print(f"Working directory: {pf_out_dir}")

    run = Run.from_definition(runscript_path)
    print(f"Loaded run: {run.get_name()}")

    # --- Apply overrides ---
    if args.stop_time is not None:
        run.TimingInfo.StopTime = args.stop_time
        print(f"StopTime overridden to {args.stop_time} hours")

    run.Solver.CLM.MetFileName = args.met_file_name
    run.Solver.CLM.MetFilePath = forcing_dir
    run.Solver.PrintEvapTrans = True

    # --- Execute ---
    print("Starting ParFlow run...\n")
    run.run(working_directory=pf_out_dir)


if __name__ == "__main__":
    main()
