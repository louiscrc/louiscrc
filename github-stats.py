import os
import sys
import requests
from collections import Counter
from datetime import datetime, timedelta, timezone

GITHUB_TOKEN = os.getenv('GH_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME', 'louiscrc')

if not GITHUB_TOKEN:
    print("Error: GH_TOKEN is required for fetching GitHub stats.")
    sys.exit(1)

now_utc = datetime.now(timezone.utc)
to_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
from_7_iso = (now_utc - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
from_30_iso = (now_utc - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
from_365_iso = (now_utc - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")

REPO_HISTORY_QUERY = """
query($owner: String!, $name: String!, $authorId: ID!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $authorId}) {
            pageInfo {
              hasNextPage
              endCursor
            }
            nodes {
              oid
              additions
              deletions
              committedDate
            }
          }
        }
      }
    }
  }
}
"""

query = """
query($login: String!, $from7: DateTime!, $from30: DateTime!, $from365: DateTime!, $to: DateTime!) {
  user(login: $login) {
    id
    commitsLast7Days: contributionsCollection(from: $from7, to: $to) {
      totalCommitContributions
    }
    stats30: contributionsCollection(from: $from30, to: $to) {
      totalCommitContributions
      commitContributionsByRepository(maxRepositories: 100) {
        repository {
          nameWithOwner
        }
      }
    }
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


def _parse_github_dt(s):
    if s.endswith("Z"):
        return datetime.fromisoformat(s[:-1] + "+00:00")
    return datetime.fromisoformat(s)


def _split_name_with_owner(nwo):
    owner, sep, name = nwo.partition("/")
    if not sep:
        return None, None
    return owner, name


def fetch_commit_line_totals(repo_blocks, user_node_id, from_7_iso, from_30_iso, to_iso, request_headers):
    """
    Sum additions/deletions for commits authored by the user on each repo's default branch,
    within the rolling windows. Covers direct pushes, squash merges, and other non-PR
    contribution commits (same scope as GitHub's contribution graph for commits).

    Limited to the top 100 repositories in the 30-day contribution window (GitHub API cap).
    """
    add_7 = del_7 = add_30 = del_30 = 0
    from_7_dt = _parse_github_dt(from_7_iso)
    from_30_dt = _parse_github_dt(from_30_iso)
    to_dt = _parse_github_dt(to_iso)
    seen_oids = set()

    for block in repo_blocks or []:
        repo = (block or {}).get("repository") or {}
        nwo = repo.get("nameWithOwner")
        if not nwo:
            continue
        owner, name = _split_name_with_owner(nwo)
        if not owner or not name:
            continue

        cursor = None
        for _ in range(500):
            r2 = requests.post(
                "https://api.github.com/graphql",
                json={
                    "query": REPO_HISTORY_QUERY,
                    "variables": {
                        "owner": owner,
                        "name": name,
                        "authorId": user_node_id,
                        "cursor": cursor,
                    },
                },
                headers=request_headers,
                timeout=60,
            )
            if r2.status_code != 200:
                print(
                    f"Warning: history {nwo} failed: {r2.text}",
                    file=sys.stderr,
                )
                break
            p2 = r2.json()
            if p2.get("errors"):
                print(
                    f"Warning: history {nwo} GraphQL: {p2['errors']}",
                    file=sys.stderr,
                )
                break
            repo_data = (p2.get("data") or {}).get("repository")
            if not repo_data:
                break
            dref = repo_data.get("defaultBranchRef")
            if not dref or not dref.get("target"):
                break
            hist = (dref.get("target") or {}).get("history")
            if not hist:
                break
            nodes = hist.get("nodes") or []
            if not nodes:
                break

            stop_repo = False
            for c in nodes:
                cd_raw = c.get("committedDate")
                if not cd_raw:
                    continue
                cd = _parse_github_dt(
                    cd_raw if cd_raw.endswith("Z") else cd_raw.replace("Z", "+00:00")
                )
                if cd > to_dt:
                    continue
                if cd < from_30_dt:
                    stop_repo = True
                    break
                oid = c.get("oid")
                if oid:
                    if oid in seen_oids:
                        continue
                    seen_oids.add(oid)
                a = c.get("additions") or 0
                d = c.get("deletions") or 0
                add_30 += a
                del_30 += d
                if cd >= from_7_dt:
                    add_7 += a
                    del_7 += d

            page = hist.get("pageInfo") or {}
            if stop_repo or not page.get("hasNextPage"):
                break
            cursor = page.get("endCursor")
            if not cursor:
                break

    return add_7, del_7, add_30, del_30


headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Content-Type": "application/json"
}

response = requests.post(
    "https://api.github.com/graphql",
    json={
        "query": query,
        "variables": {
            "login": GITHUB_USERNAME,
            "from7": from_7_iso,
            "from30": from_30_iso,
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
if 'errors' in data:
    print(f"GraphQL Error: {data['errors']}")
    sys.exit(1)

user = data["data"]["user"]
calendar = user["last365Days"]["contributionCalendar"]
total_contributions = calendar["totalContributions"]
weeks = calendar["weeks"]
commits_7d = user["commitsLast7Days"]["totalCommitContributions"]
stats30 = user["stats30"]
commits_30d = stats30["totalCommitContributions"]
repo_blocks = stats30["commitContributionsByRepository"]
lines_add_7d, lines_del_7d, lines_add_30d, lines_del_30d = fetch_commit_line_totals(
    repo_blocks,
    user["id"],
    from_7_iso,
    from_30_iso,
    to_iso,
    headers,
)

# Color scheme (GitHub-like)
COLORS = {
    'background': '#0d1117',
    'border': '#30363d',
    'text': '#c9d1d9',
    'level0': '#161b22',
    'level1': '#0e4429',
    'level2': '#006d32',
    'level3': '#26a641',
    'level4': '#39d353',
}

def get_contribution_level(count):
    if count == 0:
        return 'level0'
    elif count <= 3:
        return 'level1'
    elif count <= 6:
        return 'level2'
    elif count <= 9:
        return 'level3'
    else:
        return 'level4'


def compute_month_markers(grid):
    """Column index must match the contribution-cell packing (new column after each Sunday)."""
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


# Extract the grid data properly aligned to weekdays
grid = []
for week in weeks:
    for day in week['contributionDays']:
        date_str = day['date']
        count = day['contributionCount']
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        # In Python weekday() returns 0 for Monday, 6 for Sunday
        # GitHub usually starts week on Sunday, but our Gitlab script expects Monday=0
        grid.append({
            'date': date_str,
            'count': count,
            'level': get_contribution_level(count),
            'weekday': date_obj.weekday()
        })

month_markers = compute_month_markers(grid)

# SVG parameters
cell_size = 10
cell_gap = 3
margin = 20
header_height = 100
month_band = 16
cell_y0 = month_band

# Calculate dimensions
total_weeks = len(weeks)
days = 7
grid_width = total_weeks * (cell_size + cell_gap)
grid_height = days * (cell_size + cell_gap)

svg_width = grid_width + 2 * margin + 100
svg_height = grid_height + 2 * margin + header_height + month_band

# Start SVG
svg = [
    f'<svg width="{svg_width}" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">',
    f'  <rect width="{svg_width}" height="{svg_height}" fill="{COLORS["background"]}" rx="6"/>',
    '',
    '  <!-- Title -->',
    f'  <text x="{margin}" y="{margin + 20}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="18" font-weight="bold">',
    f'    GitHub Contributions',
    '  </text>',
    f'  <text x="{margin}" y="{margin + 36}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="11" opacity="0.85">',
    f'    Last 365 days',
    '  </text>',
    '',
    '  <!-- Stats: commits from contributionsCollection; +/- lines from default-branch commits (GraphQL history) -->',
    f'  <text x="{margin}" y="{margin + 54}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="12">',
    f'    Commits: {commits_7d} (7d) · {commits_30d} (30d)',
    '  </text>',
    f'  <text x="{margin}" y="{margin + 72}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="12">',
    f'    Lines (contribution commits): +{lines_add_7d} / -{lines_del_7d} (7d) · +{lines_add_30d} / -{lines_del_30d} (30d)',
    '  </text>',
    f'  <text x="{margin}" y="{margin + 90}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="12">',
    f'    Total: {total_contributions} contributions (last 365 days)',
    '  </text>',
    '',
    '  <!-- Contribution Grid -->',
    f'  <g transform="translate({margin + 30}, {margin + header_height + month_band})">',
]

# Month labels (same column packing as cells)
col_step = cell_size + cell_gap
for m in month_markers:
    cx = m["col"] * col_step + cell_size / 2
    svg.append(
        f'    <text x="{cx}" y="10" fill="{COLORS["text"]}" font-family="Arial, sans-serif" '
        f'font-size="8" text-anchor="middle">{m["text"]}</text>'
    )

# Draw day labels
days_labels = ['Mon', 'Wed', 'Fri']
for i, label in enumerate([1, 3, 5]):
    y = cell_y0 + label * (cell_size + cell_gap)
    svg.append(f'    <text x="-25" y="{y + cell_size}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="9">{days_labels[i]}</text>')

# Draw contribution cells
week = 0

for i, day in enumerate(grid):
    x = week * (cell_size + cell_gap)
    y = cell_y0 + day['weekday'] * (cell_size + cell_gap)
    color = COLORS[day['level']]
    
    svg.append(
        f'    <rect x="{x}" y="{y}" width="{cell_size}" height="{cell_size}" '
        f'fill="{color}" rx="2">'
        f'<title>{day["date"]}: {day["count"]} contributions</title></rect>'
    )
    
    if day['weekday'] == 6:  # Sunday, move to next week
        week += 1

svg.extend([
    '  </g>',
    '',
    '  <!-- Legend -->',
    f'  <g transform="translate({svg_width - 200}, {svg_height - 30})">',
    f'    <text x="0" y="10" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="9">Less</text>',
])

# Draw legend boxes
legend_levels = ['level0', 'level1', 'level2', 'level3', 'level4']
for i, level in enumerate(legend_levels):
    x = 30 + i * (cell_size + cell_gap)
    svg.append(f'    <rect x="{x}" y="0" width="{cell_size}" height="{cell_size}" fill="{COLORS[level]}" rx="2"/>')

svg.extend([
    f'    <text x="{30 + 5 * (cell_size + cell_gap) + 5}" y="10" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="9">More</text>',
    '  </g>',
    '',
    '</svg>'
])

with open("github-stats.svg", "w") as f:
    f.write('\n'.join(svg))

readme_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
gh_start = "<!-- github-metrics:start -->"
gh_end = "<!-- github-metrics:end -->"
if os.path.isfile(readme_path):
    try:
        with open(readme_path, encoding="utf-8") as rf:
            readme_text = rf.read()
        if gh_start in readme_text and gh_end in readme_text:
            gh_md = (
                f"**GitHub:** **{commits_7d}** commits (7d) · **{commits_30d}** commits (30d) · "
                f"**{total_contributions}** contributions (365d). "
                f"Lines (contribution commits): **+{lines_add_7d}/-{lines_del_7d}** (7d) · "
                f"**+{lines_add_30d}/-{lines_del_30d}** (30d)."
            )
            pre, rest = readme_text.split(gh_start, 1)
            _, post = rest.split(gh_end, 1)
            new_readme = f"{pre}{gh_start}\n{gh_md}\n{gh_end}{post}"
            with open(readme_path, "w", encoding="utf-8") as wf:
                wf.write(new_readme)
    except OSError as e:
        print(f"Warning: could not update README metrics: {e}", file=sys.stderr)

print("Successfully generated github-stats.svg")