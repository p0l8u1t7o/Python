"""Bounded, multi-seed numerical inverse kinematics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation

from .chain import Chain, transform_error


@dataclass(frozen=True, slots=True)
class IKResult:
    success: bool
    joints: np.ndarray
    position_error_mm: float
    orientation_error_deg: float
    nearest_distance_mm: float
    iterations: int
    message: str

    @property
    def joints_deg(self) -> list[float]:
        return self.joints.tolist()


def solve_ik(
    chain: Chain,
    target: np.ndarray,
    initial: Sequence[float] | None = None,
    *,
    position_tolerance_mm: float = 0.5,
    orientation_tolerance_deg: float = 0.5,
    max_nfev: int = 500,
    seed_count: int = 12,
) -> IKResult:
    """Solve a TCP target while enforcing every active joint limit."""

    target = np.asarray(target, dtype=float)
    if target.shape != (4, 4):
        raise ValueError("IK 目標必須是 4×4 變換矩陣")
    limits = chain.limits
    lower, upper = limits[:, 0], limits[:, 1]
    finite_lower = np.where(np.isfinite(lower), lower, -1e6)
    finite_upper = np.where(np.isfinite(upper), upper, 1e6)
    midpoint = (finite_lower + finite_upper) / 2.0
    position_scale = max(
        100.0,
        float(np.linalg.norm(chain.fk(midpoint)[:3, 3])) * 0.25,
    )

    def residual(values: np.ndarray) -> np.ndarray:
        actual = chain.fk(values)
        translation = (actual[:3, 3] - target[:3, 3]) / position_scale
        relative = target[:3, :3] @ actual[:3, :3].T
        rotation = Rotation.from_matrix(relative).as_rotvec()
        return np.concatenate((translation, rotation))

    seeds: list[np.ndarray] = []
    if initial is not None:
        candidate = np.asarray(initial, dtype=float)
        if candidate.shape != midpoint.shape:
            raise ValueError(f"IK 初始值應有 {len(midpoint)} 個關節值")
        seeds.append(np.clip(candidate, finite_lower, finite_upper))
    seeds.extend([np.clip(np.zeros_like(midpoint), finite_lower, finite_upper), midpoint])
    rng = np.random.default_rng(0xCE11F0)
    for _ in range(max(0, seed_count - len(seeds))):
        seeds.append(rng.uniform(finite_lower, finite_upper))

    best = None
    best_metric = float("inf")
    total_evaluations = 0
    for seed in seeds:
        solved = least_squares(
            residual,
            seed,
            bounds=(finite_lower, finite_upper),
            xtol=1e-12,
            ftol=1e-12,
            gtol=1e-12,
            max_nfev=max_nfev,
            x_scale="jac",
        )
        total_evaluations += solved.nfev
        position_error, orientation_error = transform_error(chain.fk(solved.x), target)
        metric = (
            position_error / position_tolerance_mm + orientation_error / orientation_tolerance_deg
        )
        if metric < best_metric:
            best = (solved.x.copy(), position_error, orientation_error)
            best_metric = metric
        if position_error < position_tolerance_mm and orientation_error < orientation_tolerance_deg:
            break

    assert best is not None
    values, position_error, orientation_error = best
    success = (
        position_error < position_tolerance_mm and orientation_error < orientation_tolerance_deg
    )
    return IKResult(
        success=success,
        joints=values,
        position_error_mm=position_error,
        orientation_error_deg=orientation_error,
        nearest_distance_mm=position_error,
        iterations=total_evaluations,
        message="IK 求解成功" if success else "目標超出可達範圍，已回傳最近姿態",
    )


inverse_kinematics = solve_ik
