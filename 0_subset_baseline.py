"""
Subset CONUS2 domain and configure a baseline ParFlow-CLM transient run.

Steps:
  1. Define HUC-based i/j bounding box
  2. Write mask and solid file
  3. Subset static ParFlow inputs
  4. Configure CLM drivers
  5. Subset climate forcing
  6. Edit reference runscript for the subset domain
  7. Copy static files to run directory
  8. Update filename values in runscript
  9. Distribute inputs across processor topology
"""

import argparse
import os

import hf_hydrodata as hf
import subsettools as st
from parflow.tools.fs import mkdir


def parse_args():
    parser = argparse.ArgumentParser(
        description="Subset CONUS2 and configure a baseline ParFlow-CLM run.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # --- Identity / authentication ---
    parser.add_argument("--email", required=True, help="HydroData account email")
    parser.add_argument("--pin", required=True, help="HydroData API pin")

    # --- Domain ---
    parser.add_argument(
        "--hucs",
        nargs="+",
        default=["02080203"],
        metavar="HUC",
        help="One or more HUC8 IDs to subset",
    )
    parser.add_argument("--grid", default="conus2", help="CONUS grid (conus1 or conus2)")

    # --- Time range ---
    parser.add_argument("--start", default="2005-10-01", help="Run start date (YYYY-MM-DD)")
    parser.add_argument("--end", default="2005-10-03", help="Run end date (YYYY-MM-DD)")

    # --- Datasets ---
    parser.add_argument(
        "--var-ds", default="conus2_domain", help="Static variable dataset name in HydroData"
    )
    parser.add_argument(
        "--forcing-ds", default="CW3E", help="Climate forcing dataset name in HydroData"
    )

    # --- Run identity ---
    parser.add_argument("--runname", default="conus2_run", help="Name for the ParFlow run")

    # --- Processor topology ---
    parser.add_argument("--topo-p", type=int, default=1, help="Processor topology P")
    parser.add_argument("--topo-q", type=int, default=1, help="Processor topology Q")

    # --- Directories ---
    parser.add_argument(
        "--base-dir", default="./run", help="Base directory for all run inputs and outputs"
    )

    return parser.parse_args()


def main():
    args = parse_args()

    # --- Authentication ---
    hf.register_api_pin(args.email, args.pin)

    os.environ.setdefault("PARFLOW_DIR", "/usr/local/")

    # --- Derive directory structure ---
    water_year = args.end[:4]
    run_tag = f"{args.runname}_{args.grid}_{water_year}WY"

    input_dir = os.path.join(args.base_dir, "inputs", run_tag)
    static_write_dir = os.path.join(input_dir, "static")
    forcing_dir = os.path.join(input_dir, "forcing")
    pf_out_dir = os.path.join(args.base_dir, "outputs", run_tag)

    for d in (static_write_dir, forcing_dir, pf_out_dir):
        mkdir(d)

    # --- Step 1: Get i/j bounding box from HUCs ---
    print(f"\n[1] Defining HUC domain for: {args.hucs}")
    ij_bounds, mask = st.define_huc_domain(hucs=args.hucs, grid=args.grid)
    ni = ij_bounds[2] - ij_bounds[0]
    nj = ij_bounds[3] - ij_bounds[1]
    print(f"    ij_bounds [imin, jmin, imax, jmax]: {ij_bounds}")
    print(f"    Grid size: ni={ni}, nj={nj}")

    # --- Step 2: Write mask and solid file ---
    print("\n[2] Writing mask and solid file...")
    st.write_mask_solid(mask=mask, grid=args.grid, write_dir=static_write_dir)

    # --- Step 3: Subset static inputs ---
    print("\n[3] Subsetting static ParFlow inputs...")
    static_paths = st.subset_static(
        ij_bounds, dataset=args.var_ds, write_dir=static_write_dir
    )

    # --- Step 4: Configure CLM drivers ---
    print("\n[4] Configuring CLM drivers...")
    st.config_clm(
        ij_bounds,
        start=args.start,
        end=args.end,
        dataset=args.var_ds,
        write_dir=static_write_dir,
    )

    # --- Step 5: Subset climate forcing ---
    print("\n[5] Subsetting climate forcing...")
    st.subset_forcing(
        ij_bounds,
        grid=args.grid,
        start=args.start,
        end=args.end,
        dataset=args.forcing_ds,
        write_dir=forcing_dir,
    )

    # --- Step 6: Load template runscript and configure for subset ---
    print("\n[6] Configuring runscript for subset domain...")
    reference_run = st.get_template_runscript(args.grid, "transient", "solid", pf_out_dir)
    runscript_path = st.edit_runscript_for_subset(
        ij_bounds,
        runscript_path=reference_run,
        runname=args.runname,
        forcing_dir=forcing_dir,
    )

    # --- Step 7: Copy static files to run directory ---
    print("\n[7] Copying static files to run directory...")
    st.copy_files(read_dir=static_write_dir, write_dir=pf_out_dir)

    # --- Step 8: Update filename values in runscript ---
    print("\n[8] Updating filename values in runscript...")
    init_press_path = os.path.basename(static_paths["ss_pressure_head"])
    depth_to_bedrock_path = os.path.basename(static_paths["pf_flowbarrier"])
    runscript_path = st.change_filename_values(
        runscript_path=runscript_path,
        init_press=init_press_path,
        depth_to_bedrock=depth_to_bedrock_path,
    )

    # --- Step 9: Distribute inputs across processor topology ---
    print(f"\n[9] Distributing inputs (P={args.topo_p}, Q={args.topo_q})...")
    st.dist_run(
        topo_p=args.topo_p,
        topo_q=args.topo_q,
        runscript_path=runscript_path,
        dist_clim_forcing=True,
    )

    print(f"\nDone. Run directory: {pf_out_dir}")
    print(f"Runscript:          {runscript_path}")


if __name__ == "__main__":
    main()
