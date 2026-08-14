# ParFlow CONUS2 Emulator

Tools for subsetting the CONUS2 domain, running baseline ParFlow-CLM transient simulations, and generating perturbed ensembles for machine learning experiments.

## Workflow

```
0_subset_baseline.py   →   1_run_baseline.py   →   2_run_ensemble.py   →   3_visualize_ensemble.py
      (subset)               (single run)            (N perturbed runs)        (diagnostic plots)
```

`0_subset_baseline.py` must be run first. Scripts `1` and `2` are independent of each other — run either or both using the same path arguments. `3_visualize_ensemble.py` reads whatever `2_run_ensemble.py` has already written.

---

## Prerequisites

- ParFlow built with MPI and Hypre (see [Building ParFlow](#building-parflow))
- `subsettools`, `hf_hydrodata`, `parflow` Python packages
- A registered HydroData account (email + PIN)

---

## Scripts

### `0_subset_baseline.py` — Subset and configure

Downloads and subsets CONUS2 static inputs, CLM drivers, and climate forcing for a HUC-defined domain. Configures and distributes the baseline runscript.

```bash
python 0_subset_baseline.py \
  --email YOUR_EMAIL \
  --pin YOUR_PIN \
  --hucs 02080203 \
  --runname my_run \
  --start 2005-10-01 \
  --end   2005-10-03 \
  --base-dir ./run
```

**Arguments**

| Argument | Default | Description |
|---|---|---|
| `--email` | *(required)* | HydroData account email |
| `--pin` | *(required)* | HydroData API PIN |
| `--hucs` | `02080203` | One or more HUC8 IDs |
| `--grid` | `conus2` | Grid (`conus1` or `conus2`) |
| `--start` | `2005-10-01` | Run start date |
| `--end` | `2005-10-03` | Run end date (also determines water year label) |
| `--var-ds` | `conus2_domain` | Static variable dataset |
| `--forcing-ds` | `CW3E` | Climate forcing dataset |
| `--runname` | `conus2_run` | Name for the ParFlow run |
| `--topo-p` | `1` | Processor topology P (X direction) |
| `--topo-q` | `1` | Processor topology Q (Y direction) |
| `--base-dir` | `./run` | Root directory for all inputs and outputs |

**Output layout**

```
{base_dir}/
  inputs/{runname}_{grid}_{year}WY/
    static/      # subsetted pfb files + .dist files
    forcing/     # climate forcing pfb files + .dist files
  outputs/{runname}_{grid}_{year}WY/
    {runname}.yaml
    *.pfb
```

**Multi-core runs**

`--topo-p` and `--topo-q` define the processor grid; total cores = P×Q. Re-run this script with updated topology values to redistribute files before changing core count.

---

### `1_run_baseline.py` — Run baseline

Loads the runscript produced by `0_subset_baseline.py` and executes a single ParFlow-CLM run. Pass the same `--runname`, `--grid`, `--end`, and `--base-dir` to resolve paths consistently.

```bash
python 1_run_baseline.py \
  --runname my_run \
  --end 2005-10-03 \
  --base-dir ./run
```

**Arguments**

| Argument | Default | Description |
|---|---|---|
| `--runname` | `conus2_run` | Must match `0_subset_baseline.py` |
| `--grid` | `conus2` | Must match `0_subset_baseline.py` |
| `--end` | `2005-10-03` | Must match `0_subset_baseline.py` |
| `--base-dir` | `./run` | Must match `0_subset_baseline.py` |
| `--stop-time` | *(from runscript)* | Override `TimingInfo.StopTime` in hours |
| `--met-file-name` | `CW3E` | CLM forcing file root name |

**Outputs written to** `{base_dir}/outputs/{runname}_{grid}_{year}WY/`:

- `{runname}.out.press.*.pfb` — pressure head at each timestep
- `{runname}.out.satur.*.pfb` — saturation
- `{runname}.out.evaptrans.*.pfb` — evapotranspiration
- `{runname}.out.clm_output.*.pfb` — full CLM output bundle

---

### `2_run_ensemble.py` — Run ensemble

Generates N perturbed ensemble members from the baseline. Each member gets its own isolated directory with a perturbation record alongside its raw outputs.

```bash
# Perturb both indicator and parameters, 20 members, Potts method
python 2_run_ensemble.py \
  --runname my_run \
  --end 2005-10-03 \
  --base-dir ./run \
  --n-ensemble 20 \
  --modify-indicator \
  --modify-parameters \
  --perturbation-method potts \
  --seed 42
```

**Arguments**

| Argument | Default | Description |
|---|---|---|
| `--runname` | `conus2_run` | Must match `0_subset_baseline.py` |
| `--grid` | `conus2` | Must match `0_subset_baseline.py` |
| `--end` | `2005-10-03` | Must match `0_subset_baseline.py` |
| `--base-dir` | `./run` | Must match `0_subset_baseline.py` |
| `--n-ensemble` | `10` | Number of ensemble members |
| `--modify-indicator` | off | Perturb the indicator field |
| `--modify-parameters` | off | Perturb subsurface parameters (Ksat, porosity) |
| `--perturbation-method` | `potts` | `potts` or `gaussian` — applied to both |
| `--potts-steps` | `100000` | MCMC steps per z-layer (Potts only) |
| `--potts-temperature` | `5.0` | Potts temperature parameter |
| `--param-scale` | `0.25` | Std dev as fraction of default value (gaussian); half-range fraction (potts) |
| `--stop-time` | *(from runscript)* | Override `TimingInfo.StopTime` in hours |
| `--topo-p` | `1` | Processor topology P |
| `--topo-q` | `1` | Processor topology Q |
| `--seed` | *(none)* | NumPy random seed for reproducibility |

**Output layout**

```
{base_dir}/ensemble/
  metadata.csv                  # one row per member: method, flags, scalar params
  member_0000/
    perturbation.json           # complete record of perturbations applied
    pf_indicator.pfb            # perturbed indicator (if --modify-indicator)
    {runname}.yaml              # runscript copy
    {runname}.out.press.*.pfb
    {runname}.out.satur.*.pfb
    {runname}.out.evaptrans.*.pfb
    {runname}.out.clm_output.*.pfb
  member_0001/
    ...
```

`metadata.csv` is the entry point for post-processing — iterate over `member_dir` values and read `perturbation.json` alongside the pfbs. Full geom unit parameters (per-unit Ksat and porosity) are stored in `perturbation.json` under `geom_params`; scalar summary values appear in `metadata.csv`.

**Perturbation methods**

| Method | Indicator | Parameters |
|---|---|---|
| `potts` | Potts MCMC — swaps geologic unit labels while preserving spatial correlation structure | Metropolis-Hastings selection among discrete states around the default value |
| `gaussian` | Adds Gaussian noise then snaps to nearest valid class label | Independent `Normal(default, scale × default)` per unit |

Subsurface parameter targets (Ksat, porosity) are discovered dynamically from the loaded runscript — no hardcoded geometry names — so this works for both CONUS1 and CONUS2.

---

### `3_visualize_ensemble.py` — Plot ensemble diagnostics

Reads the member directories written by `2_run_ensemble.py` and writes a set of PNG diagnostics. Nothing is modified; run it as often as you like.

```bash
python 3_visualize_ensemble.py \
  --runname my_run \
  --end 2005-10-03 \
  --base-dir ./run
```

**Arguments**

| Argument | Default | Description |
|---|---|---|
| `--runname` | `conus2_run` | Must match `0_subset_baseline.py` |
| `--grid` | `conus2` | Must match `0_subset_baseline.py` |
| `--end` | `2005-10-03` | Must match `0_subset_baseline.py` |
| `--base-dir` | `./run` | Must match `0_subset_baseline.py` |
| `--out-dir` | `{base_dir}/ensemble/figures` | Where the PNGs are written |
| `--layer` | `-1` | z index shown in map views; `-1` is the top (land surface) layer |
| `--max-members` | *(all)* | Plot only the first N members |
| `--time-stride` | `1` | Read every Nth pressure file for the timeseries |
| `--skip-timeseries` | off | Skip the pressure timeseries (the only slow part) |
| `--dpi` | `150` | Figure resolution |

**Figures**

| File | Content |
|---|---|
| `indicator_maps.png` | Baseline + per-member indicator field, one panel each, shared class colorbar |
| `indicator_change.png` | Cells whose geologic unit differs from the baseline, with % of layer and % of active volume changed |
| `param_map_perm.png` | Realized `log10` permeability field per member, shared color scale |
| `param_map_porosity.png` | Realized porosity field per member, shared color scale |
| `param_spread.png` | Per-geom-unit Ksat and porosity draws across members, against the baseline value |
| `pressure_timeseries.png` | Mean pressure head vs time — whole domain and surface layer — one line per member plus the ensemble mean |

Inactive cells are masked out everywhere using `{runname}.out.mask.pfb`; ParFlow fills them with a `-3.4e38` sentinel that would otherwise destroy every average.

Member directories are discovered on disk rather than read from `metadata.csv`, whose `member_dir` column stores absolute paths from the machine that ran the ensemble and goes stale as soon as the run tree moves.

The timeseries reads every pressure file for every member. For a full water year (8761 hourly steps) that is ~90k reads across a 10-member ensemble; pass `--time-stride 6` or `--skip-timeseries` while iterating on the other figures.

---

## Building ParFlow

The system `hypre-devel` package is built without MPI and will cause a `MPI_Comm` type conflict. Build Hypre from source with MPI before building ParFlow:

```bash
# Build Hypre with OpenMPI
cd packages
wget https://github.com/hypre-space/hypre/archive/refs/tags/v2.24.0.tar.gz
tar xf v2.24.0.tar.gz && cd hypre-2.24.0/src
./configure --prefix=$(pwd)/../../hypre \
            --with-MPI \
            --with-MPI-include=/usr/include/openmpi-x86_64 \
            --with-MPI-lib-dirs=/usr/lib64/openmpi/lib \
            --with-MPI-libs="mpi"
make -j$(nproc) install

# Build ParFlow
module load mpi/openmpi-x86_64
cd ../../parflow/build
bash build.sh
make -j$(nproc) install
```

The build script at [parflow/build/build.sh](parflow/build/build.sh) already includes `-DHYPRE_ROOT` pointing to the local Hypre build.
