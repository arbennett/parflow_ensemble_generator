"""
Run an ensemble of perturbed ParFlow-CLM simulations.

Reads the subsetted domain produced by 0_subset_baseline.py. For each member:
  1. Copy baseline static files to a dedicated member directory
  2. Optionally perturb the indicator field and/or subsurface parameters
  3. Redistribute perturbed files and run ParFlow
  4. Write a perturbation.json recording exactly what was used

All raw pfb outputs are preserved in each member directory. No post-processing
is performed here.

Directory layout:
  {base_dir}/ensemble/
    metadata.csv
    member_0000/
      perturbation.json
      pf_indicator.pfb  (perturbed copy)
      <runname>.yaml
      <runname>.out.press.*.pfb
      ...
    member_0001/
      ...
"""

import argparse
import csv
import json
import os
import shutil

import numpy as np
from parflow import Run
from parflow.tools.fs import mkdir
from parflow.tools.io import read_pfb, write_pfb
from parflow.tools.settings import set_working_directory
import subsettools as st

from src.perturbations import perturb_indicator, perturb_parameters


STATIC_FILES = [
    "slope_x.pfb",
    "slope_y.pfb",
    "pf_indicator.pfb",
    "mannings.pfb",
    "pf_flowbarrier.pfb",
    "pme.pfb",
    "ss_pressure_head.pfb",
    "mask.pfb",
    "solidfile.pfsol",
    "drv_clmin.dat",
    "drv_vegm.dat",
    "drv_vegp.dat",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run an ensemble of perturbed ParFlow-CLM simulations.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Path resolution (must match 0_subset_baseline.py) ---
    parser.add_argument("--runname", default="conus2_run")
    parser.add_argument("--grid", default="conus2")
    parser.add_argument("--end", default="2005-10-03", help="Run end date; used to derive water year")
    parser.add_argument("--base-dir", default="./run")

    # --- Ensemble ---
    parser.add_argument("--n-ensemble", type=int, default=10, help="Number of ensemble members")
    parser.add_argument("--modify-indicator", action="store_true", help="Perturb indicator field")
    parser.add_argument("--modify-parameters", action="store_true", help="Perturb subsurface parameters")
    parser.add_argument(
        "--perturbation-method",
        choices=["potts", "gaussian"],
        default="potts",
        help="Perturbation method applied to both indicator and parameters",
    )

    # --- Perturbation hyperparameters ---
    parser.add_argument("--potts-steps", type=int, default=100_000)
    parser.add_argument("--potts-temperature", type=float, default=5.0)
    parser.add_argument("--param-scale", type=float, default=0.25,
                        help="Std dev as fraction of default value (gaussian) or half-range (potts)")

    # --- Run config ---
    parser.add_argument("--stop-time", type=float, default=None)
    parser.add_argument("--topo-p", type=int, default=1)
    parser.add_argument("--topo-q", type=int, default=1)
    parser.add_argument(
        "--emulator",
        choices=["on", "off"],
        default="off",
        help="Toggle emulator mode",
    )
    parser.add_argument(
        "--emulator-model-path",
        default=None,
        help="Path to emulator model file",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

    return parser.parse_args()


def resolve_paths(args):
    water_year = args.end[:4]
    run_tag = f"{args.runname}_{args.grid}_{water_year}WY"
    base_dir = os.path.abspath(args.base_dir)
    return {
        "static_dir": os.path.join(base_dir, "inputs", run_tag, "static"),
        "forcing_dir": os.path.join(base_dir, "inputs", run_tag, "forcing"),
        "baseline_runscript": os.path.join(base_dir, "outputs", run_tag, f"{args.runname}.yaml"),
        "ensemble_dir": os.path.join(base_dir, "ensemble"),
    }


def setup_member_dir(member_dir, static_dir, baseline_runscript, runname):
    """Copy static files and runscript into the member directory."""
    mkdir(member_dir)
    for fname in STATIC_FILES:
        src = os.path.join(static_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, member_dir)
        dist = src + ".dist"
        if os.path.isfile(dist):
            shutil.copy2(dist, member_dir)
    shutil.copy2(baseline_runscript, os.path.join(member_dir, f"{runname}.yaml"))


def main():
    args = parse_args()

    os.environ.setdefault("PARFLOW_DIR", "/usr/local/")

    if args.seed is not None:
        np.random.seed(args.seed)

    if args.emulator == "on" and not args.emulator_model_path:
        raise ValueError("--emulator-model-path is required when --emulator is 'on'")

    paths = resolve_paths(args)
    ensemble_dir = paths["ensemble_dir"]
    mkdir(ensemble_dir)

    baseline_runscript = paths["baseline_runscript"]
    if not os.path.isfile(baseline_runscript):
        raise FileNotFoundError(
            f"Baseline runscript not found: {baseline_runscript}\n"
            "Run 0_subset_baseline.py first."
        )

    perturbation_kwargs = {
        "potts_temperature": args.potts_temperature,
        "potts_steps": args.potts_steps,
        "param_scale": args.param_scale,
    }

    metadata_rows = []

    for i in range(args.n_ensemble):
        member_id = f"{i:04d}"
        member_dir = os.path.join(ensemble_dir, f"member_{member_id}")
        print(f"\n[member {member_id}] Setting up in {member_dir}")

        setup_member_dir(member_dir, paths["static_dir"], baseline_runscript, args.runname)

        # --- Load run ---
        runscript_path = os.path.join(member_dir, f"{args.runname}.yaml")
        run = Run.from_definition(runscript_path)
        # Geom unit names (e.g. s1-s13 in CONUS1) are discovered dynamically from the
        # run object by src/perturbations._discover_geom_units — no hardcoding needed.
        # To inspect which units are found: print(_discover_geom_units(run))

        if args.stop_time is not None:
            run.TimingInfo.StopTime = args.stop_time

        run.Solver.CLM.MetFileName = "CW3E"
        run.Solver.CLM.MetFilePath = paths["forcing_dir"]
        run.Solver.PrintEvapTrans = True
        run.Process.Topology.P = args.topo_p
        run.Process.Topology.Q = args.topo_q

        if args.emulator == "on":
            run.Solver.TorchEnableAccelerator = True
            run.Solver.TorchModelFilePath = args.emulator_model_path
            run.Solver.TorchPrintPredictedPressure = True
            run.Solver.TorchDevice = "cuda"

        # --- Perturbations ---
        indicator_perturbed = False
        params_applied = {}

        if args.modify_indicator:
            print(f"  Perturbing indicator ({args.perturbation_method})...")
            indicator_file = os.path.join(member_dir, "pf_indicator.pfb")
            indicator = read_pfb(indicator_file)
            indicator = perturb_indicator(indicator, args.perturbation_method, **perturbation_kwargs)
            write_pfb(indicator_file, indicator, p=args.topo_p, q=args.topo_q)
            indicator_perturbed = True

        if args.modify_parameters:
            print(f"  Perturbing parameters ({args.perturbation_method})...")
            run, params_applied = perturb_parameters(
                run, args.perturbation_method, scale=args.param_scale
            )

        # --- Distribute ---
        print("  Distributing inputs...")
        st.dist_run(
            topo_p=args.topo_p,
            topo_q=args.topo_q,
            runscript_path=runscript_path,
            dist_clim_forcing=False,  # forcing already distributed by 0_subset_baseline.py
        )

        # --- Run ---
        set_working_directory(member_dir)
        print("  Running ParFlow...")
        run.run(working_directory=member_dir)

        # --- Record perturbation metadata ---
        meta = {
            "member_id": member_id,
            "seed": args.seed,
            "perturbation_method": args.perturbation_method,
            "modify_indicator": indicator_perturbed,
            "modify_parameters": bool(params_applied),
            "potts_temperature": args.potts_temperature,
            "potts_steps": args.potts_steps,
            "param_scale": args.param_scale,
            "emulator": args.emulator,
            "emulator_model_path": args.emulator_model_path,
            "geom_params": params_applied,
        }
        with open(os.path.join(member_dir, "perturbation.json"), "w") as f:
            json.dump(meta, f, indent=2)

        # Flatten for CSV (exclude nested geom_params)
        row = {k: v for k, v in meta.items() if k != "geom_params"}
        row["member_dir"] = member_dir
        metadata_rows.append(row)
        print(f"  Done.")

    # --- Write ensemble index ---
    if metadata_rows:
        csv_path = os.path.join(ensemble_dir, "metadata.csv")
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=metadata_rows[0].keys())
            writer.writeheader()
            writer.writerows(metadata_rows)
        print(f"\nEnsemble complete. Index written to {csv_path}")


if __name__ == "__main__":
    main()
