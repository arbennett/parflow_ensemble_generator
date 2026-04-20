"""
Perturbation methods for ensemble ParFlow runs.

Two methods are supported for both indicator fields and subsurface parameters:
  potts    -- Potts model MCMC (spatial structure-preserving)
  gaussian -- Independent Gaussian noise
"""

import numpy as np


# ---------------------------------------------------------------------------
# Potts model
# ---------------------------------------------------------------------------

def _potts_update(x, temperature, n_states):
    N, M = x.shape
    a = np.random.randint(1, N - 1)
    b = np.random.randint(1, M - 1)
    s = 2 * np.pi * x[a, b] / n_states
    neighbor_states = np.array([x[a + 1, b], x[a, b + 1], x[a - 1, b], x[a, b - 1]])
    neighbor_circle = 2 * np.pi * neighbor_states / n_states
    cost = np.sum(np.cos(s - neighbor_circle))
    if cost < 0 or np.random.rand() < np.exp(-cost * temperature):
        x[a, b] = np.random.choice(neighbor_states)
    return x


def _simulate_potts_2d(x, temperature, n_states, n_steps):
    out = x.copy()
    for _ in range(n_steps):
        out = _potts_update(out, temperature, n_states)
    return out


# ---------------------------------------------------------------------------
# Indicator perturbation
# ---------------------------------------------------------------------------

def perturb_indicator_potts(indicator, temperature=5.0, n_steps=100_000):
    """Potts MCMC perturbation applied independently to each z-layer."""
    out = indicator.copy()
    for z in range(indicator.shape[0]):
        layer = indicator[z]
        n_states = len(np.unique(layer))
        out[z] = _simulate_potts_2d(layer, temperature, n_states, n_steps)
    return out


def perturb_indicator_gaussian(indicator, scale=0.25):
    """
    Add Gaussian noise to each cell then snap to the nearest valid class label.
    scale is relative to the range of class indices in each layer.
    """
    out = indicator.copy().astype(float)
    for z in range(indicator.shape[0]):
        layer = indicator[z]
        classes = np.unique(layer)
        noise_std = scale * (classes.max() - classes.min() + 1)
        noisy = layer.astype(float) + np.random.normal(0, noise_std, layer.shape)
        # Snap each value to the nearest valid class
        snapped = classes[np.argmin(np.abs(noisy[:, :, None] - classes[None, None, :]), axis=2)]
        out[z] = snapped
    return out.astype(indicator.dtype)


def perturb_indicator(indicator, method, **kwargs):
    if method == "potts":
        return perturb_indicator_potts(
            indicator,
            temperature=kwargs.get("potts_temperature", 5.0),
            n_steps=kwargs.get("potts_steps", 100_000),
        )
    elif method == "gaussian":
        return perturb_indicator_gaussian(
            indicator,
            scale=kwargs.get("param_scale", 0.25),
        )
    else:
        raise ValueError(f"Unknown perturbation method: {method!r}. Choose 'potts' or 'gaussian'.")


# ---------------------------------------------------------------------------
# Subsurface parameter perturbation
# ---------------------------------------------------------------------------

def _discover_geom_units(run):
    """
    Return list of geom unit names that have both Perm.Value and Porosity.Value defined.

    Rather than hardcoding geometry names (e.g. CONUS1's s1-s13, g1-g8, b1-b2),
    this inspects the loaded Run object at runtime so it works for any grid or
    indicator scheme. To see which units are discovered for your run, add:

        from src.perturbations import _discover_geom_units
        print(_discover_geom_units(run))

    after loading the runscript.
    """
    units = []
    try:
        geom = run.Geom
        for name in dir(geom):
            unit = getattr(geom, name)
            try:
                _ = unit.Perm.Value
                _ = unit.Porosity.Value
                units.append(name)
            except AttributeError:
                pass
    except AttributeError:
        pass
    return units


def _gaussian_param(default, scale):
    return max(0.0, np.random.normal(loc=default, scale=scale * abs(default)))


def _potts_param(default, scale, n_states=5):
    """
    Discrete Potts-inspired scalar perturbation.
    Candidate states are evenly spaced in [default*(1-2*scale), default*(1+2*scale)].
    """
    lo = max(0.0, default * (1 - 2 * scale))
    hi = default * (1 + 2 * scale)
    states = np.linspace(lo, hi, n_states)
    # Cost = distance from current state; accept lower-cost state or with Boltzmann prob
    temperature = 1.0
    current = default
    s_current = np.argmin(np.abs(states - current))
    s_new = np.random.randint(0, n_states)
    cost = abs(s_new - s_current)
    if cost == 0 or np.random.rand() < np.exp(-cost * temperature):
        return float(states[s_new])
    return float(states[s_current])


def perturb_parameters(run, method, scale=0.25):
    """
    Perturb permeability and porosity for all discoverable geom units.
    Returns (run, dict of {unit: {perm, porosity}}) for metadata recording.
    """
    units = _discover_geom_units(run)
    applied = {}

    for name in units:
        unit = getattr(run.Geom, name)
        orig_perm = float(unit.Perm.Value)
        orig_poro = float(unit.Porosity.Value)

        if method == "potts":
            new_perm = _potts_param(orig_perm, scale)
            new_poro = _potts_param(orig_poro, scale)
        elif method == "gaussian":
            new_perm = _gaussian_param(orig_perm, scale)
            new_poro = _gaussian_param(orig_poro, scale)
        else:
            raise ValueError(f"Unknown perturbation method: {method!r}.")

        unit.Perm.Value = new_perm
        unit.Porosity.Value = new_poro
        applied[name] = {"perm": new_perm, "porosity": new_poro}

    return run, applied
