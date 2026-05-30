"""
Generate a PipelineGuard demo video using Pillow + ffmpeg.
Output: demo/pipelineguard_demo.mp4  (~3 min, 1080p, 30fps)
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
PAD_X, PAD_Y = 32, 32
BG = (22, 24, 32)
FG = (220, 220, 220)
DIM = (100, 100, 100)
CYAN = (97, 214, 214)
GREEN = (106, 153, 85)
YELLOW = (220, 187, 68)
RED = (240, 71, 71)
BOLD_WHITE = (255, 255, 255)
BORDER = (55, 60, 75)

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
    typing_speed: int = 1


def _l(text: str, color=FG, bold=False) -> Line:
    return Line(text, color, bold)


def _dim(text: str) -> Line:
    return Line(text, DIM)


def _cyan(text: str, bold=False) -> Line:
    return Line(text, CYAN, bold)


def _green(text: str) -> Line:
    return Line(text, GREEN)


def _yellow(text: str) -> Line:
    return Line(text, YELLOW)


def _red(text: str, bold=False) -> Line:
    return Line(text, RED, bold)


# ---------------------------------------------------------------------------
# Script
# ---------------------------------------------------------------------------
SCRIPT: list[Segment] = [
    # 0 — Title card (8s)
    Segment(
        lines=[
            _l(""),
            _l(""),
            _cyan("  ██████╗ ██╗██████╗ ███████╗██╗     ██╗███╗   ██╗███████╗", bold=True),
            _cyan("  ██╔══██╗██║██╔══██╗██╔════╝██║     ██║████╗  ██║██╔════╝", bold=True),
            _cyan("  ██████╔╝██║██████╔╝█████╗  ██║     ██║██╔██╗ ██║█████╗  ", bold=True),
            _cyan("  ██╔═══╝ ██║██╔═══╝ ██╔══╝  ██║     ██║██║╚██╗██║██╔══╝  ", bold=True),
            _cyan("  ██║     ██║██║     ███████╗███████╗██║██║ ╚████║███████╗  ", bold=True),
            _cyan("  ╚═╝     ╚═╝╚═╝     ╚══════╝╚══════╝╚═╝╚═╝  ╚═══╝╚══════╝  ", bold=True),
            _l(""),
            _cyan("          ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ ", bold=True),
            _cyan("         ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗", bold=True),
            _cyan("         ██║  ███╗██║   ██║███████║██████╔╝██║  ██║", bold=True),
            _cyan("         ██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║", bold=True),
            _cyan("         ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝", bold=True),
            _cyan("          ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ", bold=True),
            _l(""),
            _dim("  AI-powered GitLab CI Diagnostics · Gemini 2.5 Flash + MCP"),
            _dim("  Google Cloud Rapid Agent Hackathon — GitLab Track"),
        ],
        hold_frames=FPS * 8,
        typing_speed=999,
    ),

    # 1 — Problem statement (14s)
    Segment(
        lines=[
            _l(""),
            _yellow("  The problem:"),
            _l(""),
            _dim("  Your GitLab pipeline just failed. Again."),
            _dim("  You open the job log. 800 lines of ANSI noise."),
            _dim("  You spend 20 minutes searching for the actual error."),
            _l(""),
            _green("  PipelineGuard reads the logs. You get the answer."),
            _l(""),
            _dim("  Three commands:  diagnose  |  watch  |  serve"),
        ],
        hold_frames=FPS * 10,
        typing_speed=1,
    ),

    # 2 — Install (8s)
    Segment(
        lines=[
            _l(""),
            _cyan("  # Setup — two steps", bold=True),
            _l(""),
            _l("  $ pip install -e .", GREEN),
            _dim("  Successfully installed pipelineguard-0.1.0"),
            _l(""),
            _l("  $ cp .env.example .env", GREEN),
            _dim("  # Set GEMINI_API_KEY (aistudio.google.com)"),
            _dim("  # Set GITLAB_TOKEN  (GitLab PAT, api + read_repository scopes)"),
        ],
        hold_frames=FPS * 5,
        typing_speed=1,
    ),

    # 3 — diagnose command (2s)
    Segment(
        lines=[
            _l(""),
            _cyan("  # One command — diagnose the latest failed pipeline", bold=True),
            _l(""),
            _l("  $ pipelineguard diagnose myorg/api-service --comment", GREEN),
        ],
        hold_frames=FPS * 2,
        typing_speed=1,
    ),

    # 4 — Mode panel (3s)
    Segment(
        lines=[
            _l(""),
            _dim("  ╭──────────────────────────────────────────────────────────────╮"),
            _cyan("  │  PipelineGuard · project myorg/api-service · latest failed   │"),
            _dim("  │  mode: GitLab MCP (official) + PipelineGuard MCP             │"),
            _dim("  ╰──────────────────────────────────────────────────────────────╯"),
            _l(""),
            _green("  ✓ Official GitLab MCP server connected"),
        ],
        hold_frames=FPS * 3,
        typing_speed=2,
    ),

    # 5 — Tool calls (10s)
    Segment(
        lines=[
            _l(""),
            _dim("  # Gemini 2.5 Flash drives the tool-call loop (≤15 iterations):"),
            _dim("  #   gl_* tools  →  Official GitLab MCP  (gitlab.com/api/v4/mcp)"),
            _dim("  #   rest        →  PipelineGuard MCP    (bundled, stdio)"),
            _l(""),
            _cyan("  → gl_list_projects({\"search\": \"api-service\"})"),
            _dim("  → list_pipelines({\"project_id\": \"myorg/api-service\", \"status\": \"failed\"})"),
            _dim("  → get_pipeline_jobs({\"project_id\": \"myorg/api-service\", \"pipeline_id\": 84321})"),
            _dim("  → get_job_log({\"project_id\": \"myorg/api-service\", \"job_id\": 198744})"),
        ],
        hold_frames=FPS * 7,
        typing_speed=1,
    ),

    # 6 — Diagnosis panel (12s)
    Segment(
        lines=[
            _l(""),
            _dim("  ╭──────────────────────────── Diagnosis ──────────────────────────────╮"),
            _red("  │ Root cause: Missing REDIS_URL env var causes ConnectionError        │", bold=True),
            _dim("  │ Category:   env_var_missing                                        │"),
            _dim("  │ Affected:   test-unit                                              │"),
            _dim("  ╰─────────────────────────────────────────────────────────────────────╯"),
            _l(""),
            _dim("  REDIS_URL exists in the local .env file but is absent from"),
            _dim("  the CI job definition. The Redis client falls back to localhost"),
            _dim("  — where no server is running in CI."),
        ],
        hold_frames=FPS * 9,
        typing_speed=2,
    ),

    # 7 — Fix table (8s)
    Segment(
        lines=[
            _l(""),
            _cyan("  Proposed Fixes", bold=True),
            _dim("  ┏━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓"),
            _dim("  ┃ File            ┃ Description                     ┃ Confidence ┃"),
            _dim("  ┡━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━┩"),
            _green("  │ .gitlab-ci.yml  │ Add REDIS_URL + redis:7 service  │  high      │"),
            _dim("  └─────────────────┴─────────────────────────────────┴────────────┘"),
        ],
        hold_frames=FPS * 5,
        typing_speed=2,
    ),

    # 8 — Diff (15s)
    Segment(
        lines=[
            _l(""),
            _cyan("  .gitlab-ci.yml diff:"),
            _l(""),
            _dim("  --- a/.gitlab-ci.yml"),
            _dim("  +++ b/.gitlab-ci.yml"),
            _dim("  @@ -12,6 +12,8 @@ test-unit:"),
            _dim("     variables:"),
            _dim("       DATABASE_URL: postgresql://postgres:postgres@postgres/testdb"),
            _green("  +    REDIS_URL: redis://redis:6379/0"),
            _dim("     services:"),
            _dim("       - postgres:15"),
            _green("  +    - redis:7"),
        ],
        hold_frames=FPS * 12,
        typing_speed=1,
    ),

    # 9 — MR comment posted (8s)
    Segment(
        lines=[
            _l(""),
            _green("  Comment posted:"),
            _dim("  https://gitlab.com/myorg/api-service/-/merge_requests/42#note_123"),
            _l(""),
            _dim("  Pipeline: https://gitlab.com/myorg/api-service/-/pipelines/84321"),
            _l(""),
            _dim("  Your team sees the diagnosis — no Slack thread needed."),
        ],
        hold_frames=FPS * 6,
        typing_speed=1,
    ),

    # 10 — Watch mode (15s)
    Segment(
        lines=[
            _l(""),
            _cyan("  # Watch mode — continuous monitoring", bold=True),
            _l(""),
            _l("  $ pipelineguard watch myorg/api-service --interval 30 --comment", GREEN),
            _l(""),
            _cyan("  PipelineGuard", bold=True),
            _dim("  watching myorg/api-service every 30s · Ctrl-C to stop"),
            _l(""),
            _dim("  [polling…]"),
            _l(""),
            _yellow("  New failure detected: pipeline #84398 — diagnosing…"),
            _green("  Done: Missing DOCKER_REGISTRY_TOKEN in deploy job"),
            _dim("  Comment posted on MR !71"),
        ],
        hold_frames=FPS * 10,
        typing_speed=1,
    ),

    # 11 — Webhook mode (10s)
    Segment(
        lines=[
            _l(""),
            _cyan("  # Webhook mode — zero-touch, event-driven", bold=True),
            _l(""),
            _l("  $ pipelineguard serve --port 8765 --comment", GREEN),
            _l(""),
            _dim("  ╭─ PipelineGuard Webhook ──────────────────────────────────────╮"),
            _dim("  │ Endpoint:        http://0.0.0.0:8765/webhook/gitlab          │"),
            _dim("  │ Post MR comment: yes                                         │"),
            _dim("  ╰──────────────────────────────────────────────────────────────╯"),
            _l(""),
            _dim("  Add this URL in GitLab → Settings → Webhooks → Pipeline events"),
            _dim("  Every failed pipeline is auto-diagnosed. No manual steps."),
        ],
        hold_frames=FPS * 7,
        typing_speed=1,
    ),

    # 12 — Architecture (20s)
    Segment(
        lines=[
            _l(""),
            _cyan("  Dual MCP architecture", bold=True),
            _l(""),
            _dim("  ┌──────────────────────────────────────────────────────────┐"),
            _cyan("  │  PipelineGuardAgent · Gemini 2.5 Flash (Vertex AI)      │"),
            _dim("  │  Tool-call loop ≤15 iter · routes by name prefix         │"),
            _dim("  └────────────────┬──────────────────────┬──────────────────┘"),
            _dim("                   │ gl_* tools            │ other tools"),
            _dim("                   ▼ StreamableHTTP        ▼ stdio subprocess"),
            _dim("  ┌────────────────────────┐  ┌───────────────────────────────┐"),
            _cyan("  │ Official GitLab MCP    │  │ PipelineGuard MCP (bundled)   │"),
            _dim("  │ gitlab.com/api/v4/mcp  │  │ list_pipelines                │"),
            _dim("  │ gl_list_projects       │  │ get_pipeline_jobs             │"),
            _dim("  │ gl_list_merge_requests │  │ get_job_log                   │"),
            _dim("  │ gl_get_project  …      │  │ create_merge_request_note     │"),
            _dim("  └──────────┬─────────────┘  └──────────────┬────────────────┘"),
            _dim("             └──────────────┬─────────────────┘"),
            _dim("                            ▼"),
            _dim("                    GitLab REST API"),
        ],
        hold_frames=FPS * 15,
        typing_speed=1,
    ),

    # 13 — Closing (10s)
    Segment(
        lines=[
            _l(""),
            _l(""),
            _cyan("  MCP makes the tools.", bold=True),
            _cyan("  Gemini makes the decisions.", bold=True),
            _cyan("  PipelineGuard makes the diagnosis.", bold=True),
            _l(""),
            _l(""),
            _dim("  github.com/64johnlee/hackathon-pipeline-guard"),
            _dim("  MIT License · pip install pipelineguard"),
            _l(""),
            _dim("  Google Cloud Rapid Agent Hackathon — GitLab Track"),
        ],
        hold_frames=FPS * 8,
        typing_speed=2,
    ),
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
            save(max(1, FPS // 3))   # ~0.33s per line reveal
        save(seg.hold_frames)

    print(f"Generated {frame_idx} frames ({frame_idx / FPS:.0f}s)")
    return frame_idx


def encode_video(frame_count: int) -> None:
    OUT_VIDEO.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(FRAMES_DIR / "frame_%06d.png"),
        "-c:v", "libx264", "-preset", "slow", "-crf", "22",
        "-pix_fmt", "yuv420p",
        "-vf", f"scale={W}:{H}",
        str(OUT_VIDEO),
    ]
    print("Encoding…")
    subprocess.run(cmd, check=True)
    mb = OUT_VIDEO.stat().st_size / 1_048_576
    print(f"Output: {OUT_VIDEO}  ({mb:.1f} MB, {frame_count / FPS:.0f}s)")


if __name__ == "__main__":
    if FRAMES_DIR.exists():
        shutil.rmtree(FRAMES_DIR)
    n = generate_frames()
    encode_video(n)
    print("Done!")
