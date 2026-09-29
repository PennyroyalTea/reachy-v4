"""Keep the head from hitting the torso.

Uses the robot's real shapes from the SDK's URDF meshes: the head shell (front,
back, glasses and lens caps) as a point cloud, and the torso shell (body_top)
as a 2 mm distance grid. The SDK's simplified collision model (one cylinder for
the head) misses the corners of a tilted head by about 10 mm, which is exactly
where the real robot touched.

The check runs on where the head will actually be, not where it is told to go:
recordings show the real head sags under its own weight when pitched down
(about 0.3 deg per commanded degree, plus ~2 mm lower).

Frames that come too close get the head lifted, then eased toward neutral if
lifting is not enough; the correction is spread out in time so it looks like
intent, not a bump.
"""

import json
import xml.etree.ElementTree as ET
from functools import lru_cache
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d, map_coordinates, maximum_filter1d
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation as R

import reachy_mini

HEAD_MESHES = {"head_front_3dprint", "head_back_3dprint", "glasses_dolder_3dprint", "lens_cap_d30_3dprint", "lens_cap_d40_3dprint", "head_mic_3dprint"}
TORSO_MESHES = {"body_top_3dprint"}
HEAD_SPACING = 0.004
GRID_RES = 0.002
GRID_CAP = 0.05  # distances beyond this are irrelevant and stored as the cap
CACHE = Path.home() / ".cache" / "reachy-embodied-emotions"

SAG_PER_DEG = 0.32  # extra pitch-down per degree of commanded pitch-down (fit on recordings)
SAG_Z_MM = -2.0


def _tf(xyz, rpy) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R.from_euler("xyz", rpy).as_matrix()
    T[:3, 3] = xyz
    return T


def _floats(s: str) -> list[float]:
    return [float(v) for v in s.split()]


def _read_stl(path: Path) -> np.ndarray:
    """Binary STL -> triangles [n, 3, 3]."""
    raw = path.read_bytes()
    n = int.from_bytes(raw[80:84], "little")
    tri = np.frombuffer(raw[84:], dtype=np.dtype([("n", "<3f4"), ("v", "<9f4"), ("a", "<u2")]), count=n)
    return tri["v"].reshape(-1, 3, 3).astype(float)


def _surface(tris: np.ndarray, spacing: float) -> np.ndarray:
    """Surface samples (vertices + area-proportional points), voxel-downsampled to `spacing`."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)
    reps = np.repeat(np.arange(len(tris)), np.maximum(1, np.ceil(area / (spacing**2 / 2)).astype(int)))
    u, v = np.random.default_rng(0).random((2, len(reps)))
    flip = u + v > 1
    u[flip], v[flip] = 1 - u[flip], 1 - v[flip]
    pts = np.vstack([a[reps] + u[:, None] * (b - a)[reps] + v[:, None] * (c - a)[reps], tris.reshape(-1, 3)])
    _, keep = np.unique(np.floor(pts / spacing).astype(np.int64), axis=0, return_index=True)
    return pts[keep]


class Model:
    """Head point cloud (xl_330 frame) and torso distance grid (body frame)."""

    def __init__(self) -> None:
        root = files(reachy_mini)
        urdf_dir = Path(str(root.joinpath("descriptions/reachy_mini/urdf")))
        urdf = ET.parse(urdf_dir / "robot.urdf").getroot()
        self.head_z_offset = json.load(open(str(root.joinpath("assets/kinematics_data.json"))))["head_z_offset"]

        joints = {j.get("name"): j for j in urdf.findall("joint")}
        o = joints["yaw_body"].find("origin")
        self.T_foot_body0 = _tf(_floats(o.get("xyz")), _floats(o.get("rpy")))
        o = joints["head_frame"].find("origin")
        self.T_head_xl = np.linalg.inv(_tf(_floats(o.get("xyz")), _floats(o.get("rpy"))))

        cache = CACHE / f"collision-{version('reachy-mini')}-v1.npz"
        if cache.exists():
            data = np.load(cache)
            self.head_pts, self.grid, self.lo = data["head_pts"], data["grid"], data["lo"]
            return

        links = {link.get("name"): link for link in urdf.findall("link")}
        head = self._link_points(links["xl_330"], HEAD_MESHES, urdf_dir, HEAD_SPACING)
        torso = self._link_points(links["body_down_3dprint"], TORSO_MESHES, urdf_dir, GRID_RES)
        self.lo = torso.min(0) - 0.045
        axes = [np.arange(a, b + GRID_RES, GRID_RES) for a, b in zip(self.lo, torso.max(0) + 0.045)]
        cells = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
        d, _ = cKDTree(torso).query(cells, distance_upper_bound=GRID_CAP)
        self.grid = np.minimum(d, GRID_CAP).reshape([len(a) for a in axes]).astype(np.float32)
        self.head_pts = head[self._reachable(head)]
        CACHE.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, head_pts=self.head_pts, grid=self.grid, lo=self.lo)

    @staticmethod
    def _link_points(link: ET.Element, names: set[str], urdf_dir: Path, spacing: float) -> np.ndarray:
        out, seen = [], set()
        for vis in link.findall("visual"):
            mesh = vis.find("geometry/mesh")
            name = mesh.get("filename").split("/")[-1] if mesh is not None else ""
            if name.removesuffix(".stl") not in names or name in seen:
                continue
            seen.add(name)
            o = vis.find("origin")
            T = _tf(_floats(o.get("xyz")), _floats(o.get("rpy")))
            out.append(_surface(_read_stl(urdf_dir / "assets" / name) @ T[:3, :3].T + T[:3, 3], spacing))
        return np.vstack(out)

    def _reachable(self, head: np.ndarray, n: int = 3000) -> np.ndarray:
        """Keep only head points that come within 30 mm of the torso in some pose across the joint ranges."""
        rng = np.random.default_rng(1)
        idx = {c: i for i, c in enumerate(["x", "y", "z", "roll", "pitch", "yaw", "body_yaw"])}
        lo_hi = [(-15, 15), (-15, 15), (-20, 25), (-30, 30), (-30, 30), (-60, 60), (-45, 45)]
        poses = np.column_stack([rng.uniform(a, b, n) for a, b in lo_hi])
        near = np.zeros(len(head), bool)
        for s in range(0, n, 200):
            near |= (self.distances(poses[s : s + 200], idx, head) < 0.03).any(0)
        return near

    def distances(self, pose: np.ndarray, idx: dict[str, int], pts: np.ndarray | None = None) -> np.ndarray:
        """[frames, points] distance (m) from each head point to the torso shell."""
        pts = self.head_pts if pts is None else pts
        n = len(pose)
        head = np.zeros((n, 4, 4))
        head[:, :3, :3] = R.from_euler("xyz", pose[:, [idx["roll"], idx["pitch"], idx["yaw"]]], degrees=True).as_matrix()
        head[:, :3, 3] = pose[:, [idx["x"], idx["y"], idx["z"]]] / 1000
        head[:, 2, 3] += self.head_z_offset
        head[:, 3, 3] = 1
        body = np.tile(np.eye(4), (n, 1, 1))
        body[:, :3, :3] = R.from_euler("z", np.radians(pose[:, idx["body_yaw"]])[:, None]).as_matrix()
        T = np.linalg.inv(self.T_foot_body0 @ body) @ head @ self.T_head_xl
        local = np.einsum("nij,mj->nmi", T[:, :3, :3], pts) + T[:, None, :3, 3]
        ijk = ((local.reshape(-1, 3) - self.lo) / GRID_RES).T
        return map_coordinates(self.grid, ijk, order=1, mode="nearest").reshape(n, -1)


@lru_cache(maxsize=1)
def model() -> Model:
    return Model()


def clearance(pose: np.ndarray, idx: dict[str, int]) -> np.ndarray:
    """Minimum head-to-torso distance in metres for each frame of a pose track (mm/deg units)."""
    return model().distances(pose, idx).min(1)


def predicted(pose: np.ndarray, idx: dict[str, int]) -> np.ndarray:
    """Where the real head ends up for a commanded pose track."""
    out = pose.copy()
    out[:, idx["pitch"]] += SAG_PER_DEG * np.maximum(pose[:, idx["pitch"]] - 2.0, 0.0)
    out[:, idx["z"]] += SAG_Z_MM
    return out


def real_clearance(pose: np.ndarray, idx: dict[str, int]) -> np.ndarray:
    return clearance(predicted(pose, idx), idx)


@lru_cache(maxsize=1)
def _kinematics():
    from reachy_mini.kinematics.analytical_kinematics import AnalyticalKinematics

    return AnalyticalKinematics(automatic_body_yaw=False)


def reachable(pose: np.ndarray, idx: dict[str, int], neutral: np.ndarray, stretch: float = 1.08) -> np.ndarray:
    """Per frame: can the Stewart platform reach this head pose, with some room to spare?

    The daemon freezes the head on an unreachable pose until the target comes back
    into range, which reads as a stall and then a jump. Testing a pose stretched 8%
    further from neutral keeps frames off the very edge of the workspace too.
    """
    p = neutral + stretch * (pose - neutral)
    head = np.zeros((len(p), 4, 4))
    head[:, :3, :3] = R.from_euler("xyz", p[:, [idx["roll"], idx["pitch"], idx["yaw"]]], degrees=True).as_matrix()
    head[:, :3, 3] = p[:, [idx["x"], idx["y"], idx["z"]]] / 1000
    head[:, 3, 3] = 1
    kin = _kinematics()
    body = np.radians(pose[:, idx["body_yaw"]])
    return np.array([not np.any(np.isnan(kin.ik(h, body_yaw=b))) for h, b in zip(head, body)])


def _spread(s: np.ndarray, rows: np.ndarray, needed: np.ndarray, dt: float) -> np.ndarray:
    """Spread per-frame corrections over time: ease in ~0.3 s early, let go smoothly."""
    win = max(1, int(0.3 / dt))
    s = gaussian_filter1d(maximum_filter1d(s, size=2 * win + 1), sigma=win / 2)
    s[rows] = np.maximum(s[rows], needed)  # smoothing must never undercut the needed correction
    return np.clip(s, 0, 1)


def make_reachable(pose: np.ndarray, idx: dict[str, int], neutral: np.ndarray, dt: float) -> tuple[np.ndarray, dict]:
    """Shrink head poses toward neutral wherever the platform could not follow them."""
    ok0 = reachable(pose, idx, neutral)
    stats = {"unreachable_frames": int((~ok0).sum())}
    if ok0.all():
        return pose, stats
    head_ch = [idx[c] for c in ("x", "y", "z", "roll", "pitch", "yaw")]

    def shrunk(p: np.ndarray, s: np.ndarray) -> np.ndarray:
        out = p.copy()
        out[:, head_ch] = neutral[head_ch] + (1 - s[:, None]) * (p[:, head_ch] - neutral[head_ch])
        return out

    rows = np.flatnonzero(~ok0)
    lo, hi = np.zeros(len(rows)), np.ones(len(rows))
    for _ in range(8):
        mid = (lo + hi) / 2
        ok = reachable(shrunk(pose[rows], mid), idx, neutral)
        hi = np.where(ok, mid, hi)
        lo = np.where(ok, lo, mid)
    s = np.zeros(len(pose))
    s[rows] = hi
    out = shrunk(pose, _spread(s, rows, hi, dt))
    stats["still_unreachable_frames"] = int((~reachable(out, idx, neutral, stretch=1.0)).sum())
    return out, stats


def make_safe(pose: np.ndarray, idx: dict[str, int], neutral: np.ndarray, dt: float, margin: float = 0.010) -> tuple[np.ndarray, dict]:
    """Lift the head (then ease toward neutral) wherever it would come within `margin` of the torso.

    Every correction is also kept reachable, so fixing a collision never creates a stall.
    """
    d0 = real_clearance(pose, idx)
    bad = d0 < margin
    stats = {"frames": len(pose), "unsafe_frames": int(bad.sum()), "min_clearance_mm": float(d0.min() * 1000)}
    if not bad.any():
        return pose, stats

    # per frame: smallest correction s in [0, 1]; s <= 0.5 lifts z by up to 14 mm,
    # beyond that also shrinks the pose toward neutral (fully neutral at s = 1)
    def corrected(p: np.ndarray, s: np.ndarray) -> np.ndarray:
        out = p.copy()
        out[:, idx["z"]] += np.clip(s / 0.5, 0, 1) * 14.0
        shrink = np.clip((s - 0.5) / 0.5, 0, 1)[:, None]
        head_ch = [idx[c] for c in ("x", "y", "z", "roll", "pitch", "yaw")]
        out[:, head_ch] = (1 - shrink) * out[:, head_ch] + shrink * (neutral[head_ch] + [0, 0, 14.0, 0, 0, 0])
        return out

    rows = np.flatnonzero(bad)
    lo, hi = np.zeros(len(rows)), np.ones(len(rows))
    sub = pose[rows]
    for _ in range(8):
        mid = (lo + hi) / 2
        cand = corrected(sub, mid)
        ok = (real_clearance(cand, idx) >= margin) & reachable(cand, idx, neutral)
        hi = np.where(ok, mid, hi)
        lo = np.where(ok, lo, mid)
    s = np.zeros(len(pose))
    s[rows] = hi
    s = _spread(s, rows, hi, dt)

    # smoothing lifts neighbouring frames too; cap it wherever that would leave the workspace
    floor = np.zeros(len(pose))
    floor[rows] = hi
    over = np.flatnonzero(~reachable(corrected(pose, s), idx, neutral))
    if len(over):
        lo_s, hi_s = floor[over], s[over]
        for _ in range(8):
            mid = (lo_s + hi_s) / 2
            ok = reachable(corrected(pose[over], mid), idx, neutral)
            lo_s = np.where(ok, mid, lo_s)
            hi_s = np.where(ok, hi_s, mid)
        s[over] = lo_s
    safe = corrected(pose, s)

    d1 = real_clearance(safe, idx)
    stats.update({"corrected_min_clearance_mm": float(d1.min() * 1000), "still_unsafe_frames": int((d1 < margin * 0.5).sum())})
    return safe, stats
