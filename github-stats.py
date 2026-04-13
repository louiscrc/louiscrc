import os
import sys
import requests
from collections import Counter
from datetime import datetime, timedelta, timezone

GITHUB_TOKEN = os.getenv("GH_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME", "louiscrc")

if not GITHUB_TOKEN:
    print("Error: GH_TOKEN is required for fetching GitHub stats.")
    sys.exit(1)

now_utc = datetime.now(timezone.utc)
to_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
from_365_iso = (now_utc - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

query = """
query($login: String!, $from365: DateTime!, $to: DateTime!) {
  user(login: $login) {
    last365Days: contributionsCollection(from: $from365, to: $to) {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
  }
}
"""

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Content-Type": "application/json",
}

response = requests.post(
    "https://api.github.com/graphql",
    json={
        "query": query,
        "variables": {
            "login": GITHUB_USERNAME,
            "from365": from_365_iso,
            "to": to_iso,
        },
    },
    headers=headers,
)

if response.status_code != 200:
    print(f"Error fetching GitHub stats: {response.text}")
    sys.exit(1)

data = response.json()
if "errors" in data:
    print(f"GraphQL Error: {data['errors']}")
    sys.exit(1)

user = data["data"]["user"]
calendar = user["last365Days"]["contributionCalendar"]
weeks = calendar["weeks"]

# Color scheme (GitHub-like)
COLORS = {
    "background": "#0d1117",
    "border": "#30363d",
    "text": "#c9d1d9",
    "level0": "#161b22",
    "level1": "#0e4429",
    "level2": "#006d32",
    "level3": "#26a641",
    "level4": "#39d353",
}


def get_contribution_level(count):
    if count == 0:
        return "level0"
    elif count <= 3:
        return "level1"
    elif count <= 6:
        return "level2"
    elif count <= 9:
        return "level3"
    else:
        return "level4"


def compute_month_markers(grid):
    """Column index must match the heatmap packing (new column after each Sunday)."""
    week = 0
    prev_key = None
    raw = []
    for day in grid:
        d = datetime.strptime(day["date"], "%Y-%m-%d").date()
        key = (d.year, d.month)
        if key != prev_key:
            raw.append((week, d))
            prev_key = key
        if day["weekday"] == 6:
            week += 1
    abbrevs = [d.strftime("%b") for _, d in raw]
    dup = {a for a, n in Counter(abbrevs).items() if n > 1}
    markers = []
    for col, d in raw:
        ab = d.strftime("%b")
        text = f"{ab} '{d.strftime('%y')}" if ab in dup else ab
        markers.append({"col": col, "text": text})
    return markers


# Extract the grid data aligned to weekdays (Mon=0)
grid = []
for week in weeks:
    for day in week["contributionDays"]:
        date_str = day["date"]
        count = day["contributionCount"]
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        grid.append(
            {
                "date": date_str,
                "count": count,
                "level": get_contribution_level(count),
                "weekday": date_obj.weekday(),
            }
        )

month_markers = compute_month_markers(grid)

counts = [d["count"] for d in grid]
legend_min = min(counts) if counts else 0
legend_max = max(counts) if counts else 0

# SVG parameters
cell_size = 10
cell_gap = 3
margin = 20
month_band = 18
border_sw = 1

total_weeks = len(weeks)
grid_width = total_weeks * (cell_size + cell_gap)
grid_height = 7 * (cell_size + cell_gap)

svg_width = grid_width + 2 * margin + 100
svg_height = grid_height + 2 * margin + month_band + 36

svg = [
    f'<svg width="{svg_width}" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">',
    f'  <rect x="{border_sw / 2}" y="{border_sw / 2}" width="{svg_width - border_sw}" '
    f'height="{svg_height - border_sw}" fill="{COLORS["background"]}" rx="6" '
    f'stroke="{COLORS["border"]}" stroke-width="{border_sw}"/>',
    "",
    "  <!-- Month labels (timeline above heatmap) -->",
    f'  <g transform="translate({margin + 30}, {margin})">',
]

col_step = cell_size + cell_gap
for m in month_markers:
    cx = m["col"] * col_step + cell_size / 2
    svg.append(
        f'    <text x="{cx}" y="{month_band - 4}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" '
        f'font-size="8" text-anchor="middle">{m["text"]}</text>'
    )

svg.append("  </g>")
svg.append(
    f'  <g transform="translate({margin + 30}, {margin + month_band})">'
)

# Weekday labels (rows Mon–Sun)
for row, wlabel in zip([0, 2, 4], ["Mon", "Wed", "Fri"]):
    y = row * (cell_size + cell_gap)
    svg.append(
        f'    <text x="-25" y="{y + cell_size}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" '
        f'font-size="9">{wlabel}</text>'
    )

week = 0
for day in grid:
    x = week * (cell_size + cell_gap)
    y = day["weekday"] * (cell_size + cell_gap)
    color = COLORS[day["level"]]
    svg.append(
        f'    <rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
        f'fill="{color}" rx="2">'
        f'<title>{day["date"]}: {day["count"]} commits</title></rect>'
    )
    if day["weekday"] == 6:
        week += 1

svg.extend(
    [
        "  </g>",
        "",
        "  <!-- Legend -->",
        f'  <g transform="translate({svg_width - 200}, {svg_height - 30})">',
        f'    <text x="0" y="10" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="9">{legend_min}</text>',
    ]
)

legend_levels = ["level0", "level1", "level2", "level3", "level4"]
for i, level in enumerate(legend_levels):
    x = 30 + i * (cell_size + cell_gap)
    svg.append(
        f'    <rect x="{x}" y="0" width="{cell_size}" height="{cell_size}" fill="{COLORS[level]}" rx="2"/>'
    )

svg.extend(
    [
        f'    <text x="{30 + 5 * (cell_size + cell_gap) + 5}" y="10" fill="{COLORS["text"]}" '
        f'font-family="Arial, sans-serif" font-size="9">{legend_max}</text>',
        "  </g>",
        "",
        "</svg>",
    ]
)

with open("github-stats.svg", "w") as f:
    f.write("\n".join(svg))

print("Successfully generated github-stats.svg")
