"""
Captcha solver using Alibaba Cloud Bailian VL model + OpenCV slider detection.
VL model classifies the captcha type. OpenCV measures slider gap precisely.
"""

from __future__ import annotations

import base64
import json
import math
import os
import random
import re
from pathlib import Path
from typing import Optional, Union

import cv2
import numpy as np
import requests

API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
# Default model: qwen-vl-max for complex visual reasoning, qwen2.5-vl-72b-instruct as fallback
MODEL = os.getenv("BAILIAN_VL_MODEL", "qwen-vl-max")

CAPTCHA_PROMPT = """Analyze this captcha verification page screenshot. It's from Anjuke (安居客), a Chinese real estate website.

Page context: {page_context}

Determine what action is needed to pass the verification:

1. If the page shows a **YiDun word-order captcha** (网易易盾 语序验证) — a modal with scattered Chinese characters (usually 4) on a background image, with instruction text like "请按语序依次点击文字":
   - Identify each Chinese character visible on the background image
   - Figure out the correct order they form a meaningful Chinese phrase (usually a 4-character idiom 成语)
   - Return the click coordinates for EACH character IN THE CORRECT ORDER
   Return: {{"type": "word_order", "description": "idiom: XXXX", "clicks": [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]}}
   where coordinates are normalized to 0-1000 range. clicks[0] is the first character to click, clicks[1] is second, etc.

2. If there's a **slider/puzzle** (滑块验证, drag a piece to fit a gap):
   Return: {{"type": "drag", "description": "...", "from_norm": [x1, y1], "to_norm": [x2, y2]}}
   where coordinates are normalized to 0-1000 range. from_norm is the slider start position, to_norm is where it needs to go.

3. If there's a **click verification** (点击验证) — a single button or target to click (NOT a word-order challenge):
   Return: {{"type": "click", "description": "...", "target_norm": [x, y]}}
   where coordinates are normalized to 0-1000 range.

4. If the page shows a **text input captcha** (traditional distorted characters you type):
   Return: {{"type": "input", "description": "text captcha", "text": "ABCD"}}

5. If the page shows **no captcha** (normal content with community listings, search results, or neighborhood cards):
   Return: {{"type": "none", "description": "no captcha detected"}}

6. If you're **unsure** what to do:
   Return: {{"type": "unknown", "description": "explain what you see"}}

ONLY return the JSON object, nothing else. Do not include markdown code blocks."""


def solve_captcha(screenshot_path: str | Path, api_key: str | None = None, page_context: str = "") -> dict:
    """Send screenshot to VL model, return parsed action dict.

    Returns dict with keys: type, description, [from_norm, to_norm, target_norm, text, clicks]
    page_context: optional info like page title to help VL classify correctly
    """
    key = api_key or os.getenv("BAILIAN_KEY", "")
    if not key:
        raise ValueError("BAILIAN_KEY not set")

    # Read and encode image
    with open(screenshot_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    prompt = CAPTCHA_PROMPT.format(page_context=page_context or "unknown")

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 200,
        "temperature": 0.1,
    }

    resp = requests.post(
        API_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"].strip()

    # Parse JSON from response (handle markdown code blocks)
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

    try:
        result = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        match = re.search(r'\{[^}]+\}', content)
        if match:
            result = json.loads(match.group())
        else:
            result = {"type": "unknown", "description": content[:200], "raw": content}

    result.setdefault("type", "unknown")
    result.setdefault("description", "")
    return result


def denorm_coord(norm_x: float, norm_y: float, width: int, height: int) -> tuple[int, int]:
    """Convert normalized (0-1000) coordinates to pixel coordinates."""
    return (int(norm_x * width / 1000), int(norm_y * height / 1000))


# ── OpenCV slider captcha solver ────────────────────────────────

def solve_slider_with_opencv(screenshot_path: str, viewport: dict | None = None) -> dict | None:
    """Analyze slider captcha screenshot with OpenCV to find exact drag distance.

    Strategy:
    1. Locate the captcha widget (centered panel with distinct edges)
    2. Extract the puzzle image area and slider track
    3. Use edge-based gap detection to find the puzzle gap position
    4. Compute the drag distance in viewport pixels

    Returns dict with keys: slider_x, slider_y, track_start_x, track_end_x,
    gap_ratio, drag_pixels — or None if detection fails.
    """
    img = cv2.imread(str(screenshot_path))
    if img is None:
        return None

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── Step 1: Locate the captcha widget ────────────────────────
    # The captcha is a centered panel with visible border/shadow.
    # Use edge detection + contour analysis to find the panel rectangle.

    edges = cv2.Canny(gray, 40, 120)
    # Dilate to connect nearby edges
    kernel = np.ones((3, 3), np.uint8)
    edges_dilated = cv2.dilate(edges, kernel, iterations=1)

    contours, _ = cv2.findContours(edges_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Find candidate panels: moderate size, roughly centered, rectangular
    candidates = []
    for c in contours:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        # Panel should be 300-700px wide, 200-500px tall, centered horizontally
        if 250 < cw < 800 and 200 < ch < 500:
            center_x = x + cw // 2
            if abs(center_x - w // 2) < w // 3:  # Roughly centered
                # Score by rectangularity
                rect_area = cw * ch
                contour_area = cv2.contourArea(c)
                rectangularity = contour_area / rect_area if rect_area > 0 else 0
                score = area * rectangularity
                candidates.append((score, x, y, cw, ch))

    if not candidates:
        return None

    candidates.sort(reverse=True)
    _, px, py, pw, ph = candidates[0]

    # ── Step 2: Separate puzzle image and slider track ───────────
    panel = gray[py:py + ph, px:px + pw]

    # The puzzle image occupies the upper ~65% of the panel
    # The slider track is in the lower ~35%
    puzzle_h = int(ph * 0.62)
    track_start_y = int(ph * 0.72)
    track_end_y = ph - 5

    puzzle = panel[:puzzle_h, :]
    track_area = panel[track_start_y:track_end_y, :]

    if puzzle.size == 0 or track_area.size == 0:
        return None

    # ── Step 3: Find the slider track ────────────────────────────
    # The slider track is a long horizontal bar
    track_edges = cv2.Canny(track_area, 30, 80)
    lines = cv2.HoughLinesP(track_edges, 1, np.pi / 180, threshold=50,
                            minLineLength=int(pw * 0.4), maxLineGap=15)

    if lines is None or len(lines) == 0:
        return None

    # Normalize across OpenCV versions: v4 returns (N,1,4), v5 returns (N,4)
    if hasattr(lines, 'shape') and len(lines.shape) == 3:
        lines = lines[:, 0, :]

    # Find the longest horizontal line (the track)
    best_line = None
    best_len = 0
    for line in lines:
        x1, y1, x2, y2 = int(line[0]), int(line[1]), int(line[2]), int(line[3])
        if abs(y1 - y2) < 8:
            line_len = abs(x2 - x1)
            if line_len > best_len:
                best_len = line_len
                best_line = (min(x1, x2), (y1 + y2) // 2, max(x1, x2), (y1 + y2) // 2)

    if best_line is None:
        return None

    track_x1, track_ty, track_x2, _ = best_line
    track_width = track_x2 - track_x1

    # Track position in viewport coordinates
    track_start_vp_x = px + track_x1
    track_vp_y = py + track_start_y + track_ty

    # ── Step 4: Find the slider button ───────────────────────────
    # The button is a small rectangle on the track, usually at the left end
    # Search for a rectangular object on the track line
    button_roi_y1 = max(0, track_ty - 35)
    button_roi_y2 = min(track_area.shape[0], track_ty + 35)
    button_roi = track_area[button_roi_y1:button_roi_y2, track_x1:track_x2]

    button_edges = cv2.Canny(button_roi, 40, 100)
    button_contours, _ = cv2.findContours(button_edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    button_vp_x = px + track_x1 + 30  # Default: ~30px from track start
    for c in button_contours:
        bx, by, bw_btn, bh = cv2.boundingRect(c)
        if 20 < bw_btn < 80 and 20 < bh < 60:
            button_vp_x = px + track_x1 + bx + bw_btn // 2
            break

    # ── Step 5: Detect the puzzle gap ────────────────────────────
    # Strategy: the gap creates a cluster of vertical edges at its location.
    # Compute the column-wise edge density and find the gap.

    puzzle_edges = cv2.Canny(puzzle, 40, 120)

    # Column-wise edge density
    col_density = np.sum(puzzle_edges > 0, axis=0).astype(float)

    # Smooth with a simple moving average
    window = max(3, pw // 30)
    kernel_smooth = np.ones(window) / window
    col_smooth = np.convolve(col_density, kernel_smooth, mode='same')

    # The gap region has high edge density compared to the surrounding area.
    # We want the CENTER of the gap, not the individual edges.
    # Use the "center of mass" of edge activity.

    # Normalize to find the "hot zone"
    if np.max(col_smooth) > 0:
        col_smooth = col_smooth / np.max(col_smooth)

    # Find contiguous regions above threshold
    threshold = 0.25
    above = col_smooth > threshold

    # Find the widest contiguous region (the gap)
    best_start, best_end = 0, 0
    best_span = 0
    in_region = False
    region_start = 0
    for i, val in enumerate(above):
        if val and not in_region:
            in_region = True
            region_start = i
        elif not val and in_region:
            in_region = False
            span = i - region_start
            if span > best_span:
                best_span = span
                best_start, best_end = region_start, i

    if best_span == 0:
        # Fallback: use weighted average of edge positions
        weights = np.maximum(col_smooth, 0)
        if np.sum(weights) > 0:
            gap_center_x = int(np.average(np.arange(len(weights)), weights=weights))
        else:
            return None
    else:
        gap_center_x = (best_start + best_end) // 2

    # ── Step 6: Compute drag distance ────────────────────────────
    # gap_center_x is in puzzle image coordinates
    # Map to track coordinates: same ratio
    gap_ratio = gap_center_x / puzzle.shape[1] if puzzle.shape[1] > 0 else 0.5
    gap_ratio = max(0.05, min(0.95, gap_ratio))  # Clamp

    # The slider button starts at the left of the track, drags to gap position
    slider_start_x = px + track_x1 + 10  # Default button start
    slider_gap_x = px + track_x1 + int(track_width * gap_ratio)
    drag_pixels = slider_gap_x - slider_start_x

    return {
        "slider_x": button_vp_x,
        "slider_y": track_vp_y,
        "track_start_x": px + track_x1,
        "track_end_x": px + track_x2,
        "gap_ratio": gap_ratio,
        "drag_pixels": max(20, drag_pixels),
    }


def generate_drag_trajectory(
    distance_px: int, duration_ms: int = 1200
) -> list[tuple[int, int, int]]:
    """Generate a human-like slider drag trajectory.

    Returns list of (x, y, time_ms) waypoints. The first point is (0, 0, 0).
    Physics model: accelerate → steady → decelerate with micro-jitter.
    """
    if distance_px <= 0:
        return [(0, 0, 0)]

    points = []
    total_steps = random.randint(25, 40)
    step_time = duration_ms / total_steps

    for i in range(total_steps + 1):
        progress = i / total_steps

        # Acceleration profile: ease-in-out with slight asymmetry
        if progress < 0.25:
            # Acceleration phase
            t = progress / 0.25
            eased = 0.5 * t * t  # Quadratic ease-in
        elif progress < 0.75:
            # Steady phase
            t = (progress - 0.25) / 0.5
            eased = 0.5 + t * 0.45  # Near-linear
        else:
            # Deceleration with overshoot correction
            t = (progress - 0.75) / 0.25
            eased = 0.95 + 0.05 * (1 - (1 - t) ** 2)  # Ease-out

        x = int(distance_px * eased)

        # Micro-jitter in y (human hand tremor)
        if random.random() < 0.15:
            y = random.randint(-1, 1)
        else:
            y = 0

        t_ms = int(i * step_time)
        points.append((x, y, t_ms))

    # Ensure last point reaches exactly the target
    points[-1] = (distance_px, points[-1][1], points[-1][2])

    return points
