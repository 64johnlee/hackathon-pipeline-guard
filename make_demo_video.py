"""
Generate a PipelineGuard demo video using Pillow + ffmpeg.
Output: demo/pipelineguard_demo.mp4  (~90s, 1280x720, 30fps)
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
W, H = 1280, 720
FPS = 30
FONT_SIZE = 16
LINE_H = 22
PAD_X, PAD_Y = 36, 36
BG = (22, 24, 32)
FG = (220, 220, 220)
DIM = (100, 100, 100)
CYAN = (97, 214, 214)
GREEN = (106, 153, 85)
YELLOW = (220, 187, 68)
RED = (240, 71, 71)
BOLD_WHITE = (255, 255, 255)
BORDER = (55, 60, 75)
ORANGE = (209, 154, 102)

FONT_PATH = "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf"
BOLD_FONT_PATH = "/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf"

FRAMES_DIR = Path("/tmp/pg_frames")
OUT_VIDEO = Path("/home/user/hackathon-pipeline-guard/demo/pipelineguard_demo.mp4")


# ---------------------------------------------------------------------------
# Segment data model
# ---------------------------------------------------------------------------
@dataclass
class Line:
    text: str
    color: tuple[int, int, int] = field(default_factory=lambda: FG)
    bold: bool = False


@dataclass
class Segment:
    lines: list[Line]
    hold_frames: int = FPS
    typing_speed: int = 1  # lines revealed per step


def _l(text: str = "", color=FG, bold: bool = False) -> Line:
    return Line(text, color, bold)

def _dim(text: str) -> Line:   return Line(text, DIM)
def _cyan(text: str, bold=False) -> Line: return Line(text, CYAN, bold)
def _green(text: str, bold=False) -> Line: return Line(text, GREEN, bold)
def _yellow(text: str) -> Line: return Line(text, YELLOW)
def _red(text: str, bold=False) -> Line:  return Line(text, RED, bold)
def _orange(text: str) -> Line: return Line(text, ORANGE)


# ---------------------------------------------------------------------------
# Script  (~90 s)
# ---------------------------------------------------------------------------
SCRIPT: list[Segment] = [

    # ── 0  Title card  (5 s) ──────────────────────────────────────────────
    Segment(lines=[
        _l(),
        _l(),
        _cyan("  ██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗", bold=True),
        _cyan("  ██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝", bold=True),
        _cyan("  ██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ", bold=True),
        _cyan("  ██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ", bold=True),
        _cyan("  ██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗  ", bold=True),
        _cyan("  ╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝  ", bold=True),
        _l(),
        _cyan("              ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ ", bold=True),
        _cyan("             ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗", bold=True),
        _cyan("             ██║  ███╗██║   ██║███████║██████╔╝██║  ██║", bold=True),
        _cyan("             ██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║", bold=True),
        _cyan("             ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝", bold=True),
        _cyan("              ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ", bold=True),
        _l(),
        _dim("    AI-powered GitLab CI Diagnostics · Gemini 2.5 Flash + dual MCP"),
        _dim("    Google Cloud Rapid Agent Hackathon — GitLab Track"),
    ], hold_frames=FPS * 5, typing_speed=999),

    # ── 1  Problem  (6 s) ─────────────────────────────────────────────────
    Segment(lines=[
        _l(),
        _yellow("  The problem:"),
        _l(),
        _dim("  Pipeline failed. 800-line log. 20 minutes hunting for the error."),
        _l(),
        _green("  PipelineGuard reads the log. Gemini finds the root cause."),
        _green("  You get a diff. Done.", bold=True),
    ], hold_frames=FPS * 5, typing_speed=1),

    # ── 2  Invoke  (3 s) ──────────────────────────────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  # One command", bold=True),
        _l(),
        _l("  $ pipelineguard diagnose myorg/api-service --comment", GREEN),
    ], hold_frames=FPS * 2, typing_speed=1),

    # ── 3  Mode panel + MCP connected  (4 s) ─────────────────────────────
    Segment(lines=[
        _l(),
        _dim("  ╭──────────────────────────────────────────────────────────────╮"),
        _cyan("  │  PipelineGuard · myorg/api-service · latest failed           │"),
        _dim("  │  mode: GitLab MCP (official) + PipelineGuard MCP             │"),
        _dim("  ╰──────────────────────────────────────────────────────────────╯"),
        _l(),
        _green("  ✓ Official GitLab MCP server connected  (gitlab.com/api/v4/mcp)"),
        _green("  ✓ PipelineGuard MCP server started       (bundled, stdio)"),
    ], hold_frames=FPS * 3, typing_speed=2),

    # ── 4  Loop iter 1 — discover project  (5 s) ─────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  ⟳ Iteration 1/15", bold=True),
        _dim('  → gl_list_projects({"search": "api-service", "owned": true})'),
        _dim('    ✓ myorg/api-service  [id: 41882]'),
    ], hold_frames=FPS * 4, typing_speed=1),

    # ── 5  Loop iter 2 — find failed pipeline  (5 s) ─────────────────────
    Segment(lines=[
        _l(),
        _cyan("  ⟳ Iteration 2/15", bold=True),
        _dim('  → list_pipelines({"project_id": "myorg/api-service", "status": "failed"})'),
        _dim('    ✓ pipeline #84321  ref: main  2025-05-29T14:33:11Z'),
    ], hold_frames=FPS * 4, typing_speed=1),

    # ── 6  Loop iter 3 — enumerate jobs  (5 s) ────────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  ⟳ Iteration 3/15", bold=True),
        _dim('  → get_pipeline_jobs({"project_id": "myorg/api-service", "pipeline_id": 84321})'),
        _dim('    ✓ test-unit [failed]  build [passed]  lint [passed]'),
    ], hold_frames=FPS * 4, typing_speed=1),

    # ── 7  Loop iter 4 — pull the log  (6 s) ─────────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  ⟳ Iteration 4/15", bold=True),
        _dim('  → get_job_log({"project_id": "myorg/api-service", "job_id": 198744})'),
        _dim('    ✓ 847 lines · tail:'),
        _red('      redis.exceptions.ConnectionError: Error 111 connecting to'),
        _red('      localhost:6379. Connection refused.'),
        _dim('      (in app/cache.py:47  get_redis_client())'),
    ], hold_frames=FPS * 5, typing_speed=1),

    # ── 8  Diagnosis  (10 s) ──────────────────────────────────────────────
    Segment(lines=[
        _l(),
        _dim("  ╭──────────────────────────────── Diagnosis ──────────────────────────────╮"),
        _red("  │  Root cause: REDIS_URL not declared in CI — Redis client falls back    │", bold=True),
        _red("  │             to localhost:6379 where no service runs in CI.             │", bold=True),
        _dim("  │  Category:  env_var_missing                                            │"),
        _dim("  │  Affected:  test-unit                                                  │"),
        _dim("  │  Flaky:     no                                                         │"),
        _dim("  ╰─────────────────────────────────────────────────────────────────────────╯"),
    ], hold_frames=FPS * 8, typing_speed=2),

    # ── 9  Fix diff  (12 s) ───────────────────────────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  Proposed fix  ·  .gitlab-ci.yml  (confidence: high)", bold=True),
        _l(),
        _dim("  --- a/.gitlab-ci.yml"),
        _dim("  +++ b/.gitlab-ci.yml"),
        _dim("  @@ -12,5 +12,8 @@ test-unit:"),
        _dim("     variables:"),
        _dim("       DATABASE_URL: postgresql://postgres:postgres@postgres/testdb"),
        _green("  +    REDIS_URL: redis://redis:6379/0"),
        _dim("     services:"),
        _dim("       - postgres:15"),
        _green("  +    - redis:7"),
        _l(),
        _green("  Comment posted → gitlab.com/myorg/api-service/-/merge_requests/42#note_…"),
    ], hold_frames=FPS * 10, typing_speed=1),

    # ── 10  Architecture  (15 s) ──────────────────────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  How it works — dual MCP architecture", bold=True),
        _l(),
        _dim("  ┌───────────────────────────────────────────────────────────────┐"),
        _cyan("  │  PipelineGuardAgent  ·  Gemini 2.5 Flash  ·  ≤15 iterations  │"),
        _dim("  │  Routes by tool-name prefix: gl_* → official, rest → bundled  │"),
        _dim("  └──────────────────┬────────────────────────┬────────────────────┘"),
        _dim("                     │ gl_* (StreamableHTTP)   │ stdio"),
        _dim("                     ▼                         ▼"),
        _dim("  ┌──────────────────────────┐  ┌───────────────────────────────────┐"),
        _cyan("  │ Official GitLab MCP      │  │ PipelineGuard MCP (bundled)       │"),
        _dim("  │ gitlab.com/api/v4/mcp    │  │ list_pipelines                    │"),
        _dim("  │ gl_list_projects         │  │ get_pipeline_jobs                 │"),
        _dim("  │ gl_list_merge_requests   │  │ get_job_log                       │"),
        _dim("  │ gl_create_note  …        │  │ create_merge_request_note  …      │"),
        _dim("  └──────────────────────────┘  └───────────────────────────────────┘"),
    ], hold_frames=FPS * 12, typing_speed=1),

    # ── 11  Live URL + closing  (8 s) ─────────────────────────────────────
    Segment(lines=[
        _l(),
        _cyan("  Try it live", bold=True),
        _l(),
        _green("  https://johnlee007-pipelineguard.hf.space"),
        _l(),
        _dim("  POST /webhook/gitlab  — zero-touch pipeline monitoring"),
        _dim("  POST /demo            — instant demo with real GitLab data"),
        _l(),
        _dim("  github.com/64johnlee/hackathon-pipeline-guard  ·  MIT"),
        _dim("  Google Cloud Rapid Agent Hackathon — GitLab Track"),
    ], hold_frames=FPS * 7, typing_speed=1),
]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def load_fonts():
    reg = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    bold = ImageFont.truetype(BOLD_FONT_PATH, FONT_SIZE)
    return reg, bold


def render_frame(lines: list[Line], reg, bold) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W, 28], fill=(30, 32, 42))
    draw.text((12, 6), "● ● ●  PipelineGuard Demo", font=reg, fill=DIM)
    draw.line([(0, 28), (W, 28)], fill=BORDER, width=1)

    max_lines = (H - PAD_Y * 2 - 28) // LINE_H
    visible = lines[-max_lines:] if len(lines) > max_lines else lines

    y = PAD_Y + 28
    for line in visible:
        f = bold if line.bold else reg
        draw.text((PAD_X, y), line.text, font=f, fill=line.color)
        y += LINE_H

    return img


def generate_frames() -> int:
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    reg, bold = load_fonts()
    frame_idx = 0
    accumulated: list[Line] = []

    def save(n: int = 1) -> None:
        nonlocal frame_idx
        img = render_frame(accumulated, reg, bold)
        for _ in range(n):
            img.save(FRAMES_DIR / f"frame_{frame_idx:06d}.png")
            frame_idx += 1

    for seg in SCRIPT:
        chunk = max(1, seg.typing_speed)
        pending = list(seg.lines)
        while pending:
            accumulated.extend(pending[:chunk])
            pending = pending[chunk:]
            save(max(1, FPS // 4))   # ~0.25 s per reveal step
        save(seg.hold_frames)

    print(f"Generated {frame_idx} frames ({frame_idx / FPS:.0f}s)")
    return frame_idx


def encode_video(frame_count: int) -> None:
    OUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(FRAMES_DIR / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H}",
        str(OUT_VIDEO),
    ]
    print("Encoding…")
    subprocess.run(cmd, check=True, capture_output=True)
    mb = OUT_VIDEO.stat().st_size / 1_048_576
    print(f"Output: {OUT_VIDEO}  ({mb:.1f} MB, {frame_count / FPS:.0f}s)")


if __name__ == "__main__":
    if FRAMES_DIR.exists():
        shutil.rmtree(FRAMES_DIR)
    n = generate_frames()
    encode_video(n)
    print("Done!")
