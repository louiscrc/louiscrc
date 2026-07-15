#!/usr/bin/env python3
"""
GitLab Activity Tracker
Counts commits from repository history (not the Events API) so migrated
repos keep their authored dates after an instance move.
"""

import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

# Configuration
GITLAB_USERNAME = os.getenv("GITLAB_USERNAME", "louiscrc")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
GITLAB_URL = (os.getenv("GITLAB_URL") or "https://gitlab.com").rstrip("/")
OUTPUT_FILE = "gitlab-activity.svg"
MAX_WORKERS = int(os.getenv("GITLAB_MAX_WORKERS", "8"))

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


class GitLabActivityFetcher:
    def __init__(self, username, token=None, gitlab_url="https://gitlab.com"):
        self.username = username
        self.token = token
        self.gitlab_url = gitlab_url.rstrip("/")
        self.api_url = f"{self.gitlab_url}/api/v4"
        self.headers = {}
        if token:
            self.headers["PRIVATE-TOKEN"] = token

    def get_user_id(self):
        """Resolve username → id (public users endpoint)."""
        try:
            response = requests.get(
                f"{self.api_url}/users",
                params={"username": self.username},
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()
            users = response.json()
            if users:
                return users[0]["id"]
        except Exception as e:
            print(f"Error fetching user ID: {e}", file=sys.stderr)
        return None

    def get_author_emails(self):
        """Emails linked to the authenticated account (used to attribute commits)."""
        emails = set()
        if not self.token:
            return emails

        try:
            me = requests.get(f"{self.api_url}/user", headers=self.headers, timeout=30)
            me.raise_for_status()
            profile = me.json()
            for key in ("email", "public_email", "commit_email"):
                val = (profile.get(key) or "").strip().lower()
                if val:
                    emails.add(val)
        except Exception as e:
            print(f"Warning: could not load /user profile: {e}", file=sys.stderr)

        try:
            resp = requests.get(
                f"{self.api_url}/user/emails", headers=self.headers, timeout=30
            )
            if resp.ok:
                for row in resp.json():
                    val = (row.get("email") or "").strip().lower()
                    if val:
                        emails.add(val)
        except Exception as e:
            print(f"Warning: could not load /user/emails: {e}", file=sys.stderr)

        return emails

    def get_user_projects(self):
        """Membership projects (paginated). Token required for private repos."""
        all_projects = []
        page = 1
        try:
            while page <= 50:
                params = {
                    "per_page": 100,
                    "page": page,
                    "membership": "true",
                    "simple": "true",
                }
                response = requests.get(
                    f"{self.api_url}/projects",
                    params=params,
                    headers=self.headers,
                    timeout=30,
                )
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    break
                all_projects.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
            return all_projects
        except Exception as e:
            print(f"Error fetching projects: {e}", file=sys.stderr)
            return []

    def get_project_commits(self, project_id, since_iso, author_emails):
        """Commits for one project since cutoff (all branches), filtered by author email."""
        emails = {e.lower() for e in author_emails}
        commits = []
        # Server-side author filter when possible (one email); still verify client-side.
        author_param = next(iter(emails)) if len(emails) == 1 else None
        page = 1
        try:
            while page <= 100:
                params = {
                    "since": since_iso,
                    "all": "true",
                    "per_page": 100,
                    "page": page,
                }
                if author_param:
                    params["author"] = author_param
                response = requests.get(
                    f"{self.api_url}/projects/{project_id}/repository/commits",
                    params=params,
                    headers=self.headers,
                    timeout=60,
                )
                if response.status_code in (404, 403):
                    break
                response.raise_for_status()
                batch = response.json()
                if not batch:
                    break
                for commit in batch:
                    email = (commit.get("author_email") or "").strip().lower()
                    if email in emails:
                        commits.append(commit)
                if len(batch) < 100:
                    break
                page += 1
        except Exception as e:
            print(f"Warning: commits for project {project_id}: {e}", file=sys.stderr)
        return commits

    def calculate_contributions_from_commits(self, commits, days=365):
        """Bucket commits by authored_date (preserves pre-migration history)."""
        contributions = defaultdict(int)
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        seen = set()

        for commit in commits:
            sha = commit.get("id") or commit.get("short_id")
            if sha and sha in seen:
                continue

            raw = commit.get("authored_date") or commit.get("committed_date")
            if not raw:
                continue
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if dt.astimezone(timezone.utc) < cutoff:
                continue

            if sha:
                seen.add(sha)
            contributions[dt.date().isoformat()] += 1

        return contributions, len(seen)

    def get_stats(self, days=365):
        """Build heatmap stats from repository commit history."""
        if not self.token:
            print("Error: GITLAB_TOKEN is required to read private commit history.")
            sys.exit(1)

        emails = self.get_author_emails()
        if not emails:
            print("Error: no author emails found on the authenticated GitLab user.")
            sys.exit(1)

        projects = self.get_user_projects()
        print(f"Scanning {len(projects)} projects...")

        since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        all_commits = []
        projects_with_commits = set()

        def fetch_one(project):
            pid = project["id"]
            return pid, self.get_project_commits(pid, since_iso, emails)

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = [pool.submit(fetch_one, p) for p in projects]
            done = 0
            for fut in as_completed(futures):
                pid, commits = fut.result()
                done += 1
                if commits:
                    projects_with_commits.add(pid)
                    all_commits.extend(commits)
                if done % 10 == 0 or done == len(projects):
                    print(f"  … {done}/{len(projects)}")

        contributions, unique_commits = self.calculate_contributions_from_commits(
            all_commits, days=days
        )

        return {
            "total_contributions": unique_commits,
            "total_projects": len(projects),
            "activity_projects": len(projects_with_commits),
            "daily_contributions": contributions,
        }


def get_contribution_level(count):
    if count == 0:
        return "level0"
    if count <= 3:
        return "level1"
    if count <= 6:
        return "level2"
    if count <= 9:
        return "level3"
    return "level4"


def compute_month_markers(grid):
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


def generate_contribution_grid(contributions, days=365):
    grid = []
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days - 1)

    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime("%Y-%m-%d")
        count = contributions.get(date_str, 0)
        grid.append(
            {
                "date": date_str,
                "count": count,
                "level": get_contribution_level(count),
                "weekday": current_date.weekday(),
            }
        )
        current_date += timedelta(days=1)

    return grid


def grid_week_columns(grid):
    week = 0
    max_col = 0
    for day in grid:
        max_col = max(max_col, week)
        if day["weekday"] == 6:
            week += 1
    return max_col + 1


def generate_svg(stats, width=800, height=200):
    contributions = stats["daily_contributions"]
    total_commits_365 = stats["total_contributions"]

    grid = generate_contribution_grid(contributions)
    month_markers = compute_month_markers(grid)

    counts = [d["count"] for d in grid]
    legend_min = min(counts) if counts else 0
    legend_max = max(counts) if counts else 0

    cell_size = 10
    cell_gap = 3
    margin = 20
    month_band = 18
    border_sw = 1

    num_week_cols = grid_week_columns(grid)
    grid_width = num_week_cols * (cell_size + cell_gap)
    grid_height = 7 * (cell_size + cell_gap)

    svg_width = grid_width + 2 * margin + 100
    svg_height = grid_height + 2 * margin + month_band + 36

    col_step = cell_size + cell_gap
    svg = [
        f'<svg width="{svg_width}" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">',
        f'  <rect x="{border_sw / 2}" y="{border_sw / 2}" width="{svg_width - border_sw}" '
        f'height="{svg_height - border_sw}" fill="{COLORS["background"]}" rx="6" '
        f'stroke="{COLORS["border"]}" stroke-width="{border_sw}"/>',
        "",
        "  <!-- Month labels (timeline above heatmap) -->",
        f'  <g transform="translate({margin + 30}, {margin})">',
    ]

    for m in month_markers:
        cx = m["col"] * col_step + cell_size / 2
        svg.append(
            f'    <text x="{cx}" y="{month_band - 4}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" '
            f'font-size="8" text-anchor="middle">{m["text"]}</text>'
        )

    svg.append("  </g>")
    svg.append(f'  <g transform="translate({margin + 30}, {margin + month_band})">')

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

    legend_row_y = svg_height - 20
    svg.extend(
        [
            "  </g>",
            "",
            "  <!-- Legend row: total (left), scale (right) -->",
            f'  <text x="{margin}" y="{legend_row_y}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" '
            f'font-size="8">Number of commits (365d) : {total_commits_365}</text>',
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

    return "\n".join(svg)


def main():
    print(f"Fetching GitLab activity for {GITLAB_USERNAME}...")

    fetcher = GitLabActivityFetcher(GITLAB_USERNAME, GITLAB_TOKEN, GITLAB_URL)

    user_id = fetcher.get_user_id()
    if not user_id:
        print(f"Error: Could not find user '{GITLAB_USERNAME}'")
        sys.exit(1)

    print("Fetching commit history...")
    stats = fetcher.get_stats()

    print(f"Total commits (365d): {stats['total_contributions']}")
    print(
        f"Projects: {stats['total_projects']} "
        f"(with your commits: {stats['activity_projects']})"
    )

    print(f"Generating {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w") as f:
        f.write(generate_svg(stats))

    print(f"✓ Successfully generated {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
