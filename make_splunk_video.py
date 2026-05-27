"""Generate the SplunkGuard demo video for the Splunk Agentic Ops Hackathon.

Uses the same Pillow + ffmpeg rendering pipeline as make_demo_video.py;
only the SCRIPT content and output filename differ.

Output: demo/splunkguard_demo.mp4
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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
BORDER = (55, 60, 75)

FONT_PATH = "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf"
BOLD_FONT_PATH = "/usr/share/fonts/truetype/ubuntu/UbuntuMono-B.ttf"

FRAMES_DIR = Path("/tmp/sg_frames")
OUT_VIDEO = Path("/home/user/hackathon-pipeline-guard/demo/splunkguard_demo.mp4")


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


SCRIPT: list[Segment] = [
    Segment(
        lines=[
            _l(""),
            _l(""),
            _cyan("  ███████╗██████╗ ██╗     ██╗   ██╗███╗   ██╗██╗  ██╗", bold=True),
            _cyan("  ██╔════╝██╔══██╗██║     ██║   ██║████╗  ██║██║ ██╔╝", bold=True),
            _cyan("  ███████╗██████╔╝██║     ██║   ██║██╔██╗ ██║█████╔╝ ", bold=True),
            _cyan("  ╚════██║██╔═══╝ ██║     ██║   ██║██║╚██╗██║██╔═██╗ ", bold=True),
            _cyan("  ███████║██║     ███████╗╚██████╔╝██║ ╚████║██║  ██╗", bold=True),
            _cyan("  ╚══════╝╚═╝     ╚══════╝ ╚═════╝ ╚═╝  ╚═══╝╚═╝  ╚═╝", bold=True),
            _l(""),
            _cyan("            ██████╗ ██╗   ██╗ █████╗ ██████╗ ██████╗ ", bold=True),
            _cyan("           ██╔════╝ ██║   ██║██╔══██╗██╔══██╗██╔══██╗", bold=True),
            _cyan("           ██║  ███╗██║   ██║███████║██████╔╝██║  ██║", bold=True),
            _cyan("           ██║   ██║██║   ██║██╔══██║██╔══██╗██║  ██║", bold=True),
            _cyan("           ╚██████╔╝╚██████╔╝██║  ██║██║  ██║██████╔╝", bold=True),
            _cyan("            ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ", bold=True),
            _l(""),
            _dim("  AI-powered Splunk observability · Gemini 2.5 Flash + Splunk REST"),
            _dim("  Splunk Agentic Ops Hackathon — Observability Track"),
        ],
        hold_frames=FPS * 8,
        typing_speed=999,
    ),
    Segment(
        lines=[
            _l(""),
            _yellow("  The problem:"),
            _l(""),
            _dim("  Splunk indexes everything. The hard part is asking the right question."),
            _dim("  You know the answer is in there. You just don't know the SPL."),
            _l(""),
            _green("  Ask in plain English. Gemini writes the SPL. You get the answer."),
            _l(""),
            _dim("  One command:  pipelineguard splunk investigate \"<question>\""),
        ],
        hold_frames=FPS * 8,
        typing_speed=1,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  Architecture", bold=True),
            _l(""),
            _dim("  Natural-language question"),
            _dim("       │"),
            _dim("       ▼"),
            _dim("  ┌──────────────────────────────────────────────┐"),
            _cyan("  │ SplunkGuardAgent (pipelineguard/splunk_agent)│"),
            _dim("  │ Gemini 2.5 Flash · single-call or tool loop  │"),
            _dim("  └──────────────────┬───────────────────────────┘"),
            _dim("                     │ SPL via REST (--direct, verified)"),
            _dim("                     ▼"),
            _dim("  ┌──────────────────────────────────────────────┐"),
            _cyan("  │ Splunk Enterprise / Cloud                    │"),
            _dim("  │ index=pipelineguard · gitlab:pipeline+job    │"),
            _dim("  └──────────────────────────────────────────────┘"),
            _l(""),
            _dim("  Forward-ready MCP path: Splunkbase App #7931 (when compatible)"),
        ],
        hold_frames=FPS * 10,
        typing_speed=1,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  # Setup — under 5 minutes from scratch", bold=True),
            _l(""),
            _l("  $ docker run -d --name splunk -p 8000:8000 -p 8088:8088 -p 8089:8089 \\", GREEN),
            _l("      -e SPLUNK_PASSWORD=changeme \\", GREEN),
            _l("      -e SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com \\", GREEN),
            _l("      -e SPLUNK_START_ARGS=--accept-license \\", GREEN),
            _l("      splunk/splunk:latest", GREEN),
            _dim("  e1c4f...  (Splunk healthy in ~60s)"),
            _l(""),
            _l("  $ pip install -e .", GREEN),
            _dim("  Successfully installed pipelineguard-0.1.0"),
        ],
        hold_frames=FPS * 8,
        typing_speed=1,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  # Step 1: ingest real GitLab CI/CD data into Splunk via HEC", bold=True),
            _l(""),
            _l("  $ pipelineguard splunk ingest gitlab-org/cli --since -7d --max-pipelines 30", GREEN),
            _l(""),
            _dim("  ╭─────────────────────────────────────────────────────────────╮"),
            _dim("  │  GitLab → Splunk                                            │"),
            _dim("  │  Project: gitlab-org/cli  Since: -7d                        │"),
            _dim("  │  HEC: https://localhost:8088  Index: pipelineguard          │"),
            _dim("  ╰─────────────────────────────────────────────────────────────╯"),
            _l(""),
            _cyan("              Ingest summary"),
            _dim("  ┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓"),
            _dim("  ┃ Metric               ┃ Count ┃"),
            _dim("  ┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩"),
            _green("  │ Pipelines            │    30 │"),
            _green("  │ Jobs                 │   264 │"),
            _green("  │ Events posted to HEC │   294 │"),
            _dim("  └──────────────────────┴───────┘"),
            _l(""),
            _yellow("  Real:  37 seconds, real public Splunk-Free Docker, real GitLab data."),
        ],
        hold_frames=FPS * 10,
        typing_speed=1,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  # Step 2: ask Splunk a question in plain English (MCP mode = default)", bold=True),
            _l(""),
            _l('  $ pipelineguard splunk investigate \\', GREEN),
            _l('      "What CI pipelines failed and why?" \\', GREEN),
            _l('      --earliest -30d', GREEN),
            _l(""),
            _dim("  (omit --direct to use the MCP path against Splunkbase App #7931)"),
        ],
        hold_frames=FPS * 4,
        typing_speed=1,
    ),
    Segment(
        lines=[
            _l(""),
            _dim("  ╭─────────────────────────────────────────────────────────────╮"),
            _cyan("  │  SplunkGuard · What CI pipelines failed and why?            │"),
            _dim("  │  time range: -30d → now · mode: MCP                         │"),
            _dim("  ╰─────────────────────────────────────────────────────────────╯"),
            _l(""),
            _dim("  Connecting to Splunk MCP Server at https://localhost:8089/services/mcp …"),
            _green("  Splunk MCP Server ready"),
            _l(""),
            _cyan("  Iteration 1/15 …", bold=True),
            _green("  → splunk_run_query({\"query\": \"search index=pipelineguard"),
            _green("      sourcetype=gitlab:job status=failed | stats count by"),
            _green("      failure_reason, name | sort -count\"})"),
            _l(""),
            _cyan("  Iteration 2/15 …", bold=True),
            _green("  → splunk_run_query({\"query\": \"search index=pipelineguard"),
            _green("      name=code_navigation_golang status=failed | head 5"),
            _green("      | table _time, project, failure_reason\"})"),
            _l(""),
            _dim("  Synthesizing structured report …"),
        ],
        hold_frames=FPS * 12,
        typing_speed=2,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  MCP-mode SplunkInvestigationReport (richer than --direct):", bold=True),
            _l(""),
            _dim("  {"),
            _yellow('    "root_cause":'),
            _l('      "Multiple CI pipeline jobs in \'gitlab-org/cli\' are'),
            _l('       failing due to script errors",'),
            _yellow('    "investigation_category":'),
            _green('      "pipeline_failure",'),
            _yellow('    "affected_components": ['),
            _l('      "gitlab-org/cli project",'),
            _l('      "code_navigation_golang job",     ← specific job names'),
            _l('      "tests:unit job"                  ← MCP found these'),
            _l('    ],'),
            _yellow('    "time_range":'),
            _l('      "2026-05-26 20:35 UTC – 2026-05-27 07:20 UTC",'),
            _yellow('    "is_ongoing": true,            ← MCP inferred this'),
            _yellow('    "recommended_actions": [ 3 actions with SPL ]'),
            _dim("  }"),
        ],
        hold_frames=FPS * 14,
        typing_speed=2,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  Recommended action #3 — proactive monitoring SPL:", bold=True),
            _l(""),
            _yellow("    action:"),
            _l('      "Monitor the pipelineguard index for any new CI pipeline'),
            _l('       failures, especially those with script_failure reasons."'),
            _l(""),
            _yellow("    spl_query:"),
            _green('      index=pipelineguard | spath | search status="failed"'),
            _green('      failure_reason="script_failure"'),
            _green("      | table _time, project, name, stage, status, failure_reason"),
            _l(""),
            _yellow('    confidence: "high"'),
            _l(""),
            _green("  → paste straight into a saved search / alert / Slack webhook."),
        ],
        hold_frames=FPS * 10,
        typing_speed=2,
    ),
    Segment(
        lines=[
            _l(""),
            _cyan("  Benchmark — both paths verified (2026-05-27):", bold=True),
            _l(""),
            _dim("  ┌─────────────┬─────────────┬───────┬─────────────────────────────┐"),
            _dim("  │ Mode        │ Splunk      │ Time  │ Notes                       │"),
            _dim("  ├─────────────┼─────────────┼───────┼─────────────────────────────┤"),
            _green("  │ --direct    │ 10.4.0      │ 8.48s │ 1 Gemini call, 2 SPL recs   │"),
            _green("  │ MCP #7931   │ 9.4.11      │ 37.8s │ 2 tool calls, 3 SPL recs    │"),
            _dim("  └─────────────┴─────────────┴───────┴─────────────────────────────┘"),
            _l(""),
            _cyan("  Splunk Agentic Ops — Observability + Best Use of MCP Server", bold=True),
            _l(""),
            _dim("    github.com/64johnlee/hackathon-pipeline-guard"),
            _dim("    SPLUNK.md  ·  MIT licensed"),
            _l(""),
            _dim("    Built with: Gemini 2.5 Flash · Splunk MCP Server (App #7931)"),
            _dim("    · Streamable HTTP transport · GitLab HEC ingester"),
        ],
        hold_frames=FPS * 12,
        typing_speed=1,
    ),
]


def load_fonts():
    reg = ImageFont.truetype(FONT_PATH, FONT_SIZE)
    bold = ImageFont.truetype(BOLD_FONT_PATH, FONT_SIZE)
    return reg, bold


def render_frame(lines: list[Line], reg, bold) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    draw.rectangle([0, 0, W, 28], fill=(30, 32, 42))
    draw.text((12, 6), "● ● ●  SplunkGuard Demo", font=reg, fill=DIM)
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
        accumulated = []  # fresh slate per segment
        chunk = max(1, seg.typing_speed)
        pending = list(seg.lines)
        while pending:
            accumulated.extend(pending[:chunk])
            pending = pending[chunk:]
            save(max(1, FPS // 3))
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
