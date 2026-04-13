#!/usr/bin/env python3
"""
GitLab Activity Tracker
Fetches GitLab contributions and generates an SVG visualization
"""

import requests
import json
from datetime import datetime, timedelta
from collections import Counter, defaultdict
import os
import sys

# Configuration
GITLAB_USERNAME = os.getenv('GITLAB_USERNAME', 'louiscrc')
GITLAB_TOKEN = os.getenv('GITLAB_TOKEN', '')
GITLAB_URL = os.getenv('GITLAB_URL', 'https://gitlab.com')
OUTPUT_FILE = 'gitlab-activity.svg'

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

class GitLabActivityFetcher:
    def __init__(self, username, token=None, gitlab_url='https://gitlab.com'):
        self.username = username
        self.token = token
        self.gitlab_url = gitlab_url
        self.api_url = f"{gitlab_url}/api/v4"
        self.headers = {}
        if token:
            self.headers['PRIVATE-TOKEN'] = token
    
    def get_user_id(self):
        """Get user ID from username"""
        try:
            response = requests.get(
                f"{self.api_url}/users",
                params={'username': self.username},
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            users = response.json()
            if users:
                return users[0]['id']
        except Exception as e:
            print(f"Error fetching user ID: {e}", file=sys.stderr)
        return None
    
    def get_user_events(self, user_id, days=365):
        """Fetch user events from GitLab"""
        events = []
        page = 1
        per_page = 100
        
        try:
            while len(events) < 1000:  # Limit to prevent excessive API calls
                # Use authenticated /events endpoint instead of /users/:id/events 
                # to get events across all namespaces the user has access to
                url = f"{self.api_url}/events" if self.token else f"{self.api_url}/users/{user_id}/events"
                response = requests.get(
                    url,
                    params={'per_page': per_page, 'page': page},
                    headers=self.headers,
                    timeout=10
                )
                response.raise_for_status()
                page_events = response.json()
                
                if not page_events:
                    break
                
                events.extend(page_events)
                page += 1
                
                # Check if we've gone back far enough
                if page_events:
                    oldest_date = datetime.fromisoformat(page_events[-1]['created_at'].replace('Z', '+00:00'))
                    if oldest_date < datetime.now().astimezone() - timedelta(days=days):
                        break
        except Exception as e:
            print(f"Error fetching events: {e}", file=sys.stderr)
        
        return events
    
    def get_user_projects(self, user_id):
        """Fetch user's projects (paginated). With a token, uses membership=true."""
        all_projects = []
        page = 1
        try:
            url = f"{self.api_url}/projects" if self.token else f"{self.api_url}/users/{user_id}/projects"
            while page <= 50:
                params = {"per_page": 100, "page": page}
                if self.token:
                    params["membership"] = "true"
                response = requests.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=10,
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
    
    def calculate_contributions(self, events, days=365):
        """Calculate daily contribution counts"""
        contributions = defaultdict(int)
        cutoff_date = datetime.now().astimezone() - timedelta(days=days)
        
        for event in events:
            try:
                event_date = datetime.fromisoformat(event['created_at'].replace('Z', '+00:00'))
                if event_date >= cutoff_date:
                    date_str = event_date.strftime('%Y-%m-%d')
                    contributions[date_str] += 1
            except Exception as e:
                continue
        
        return contributions

    def get_stats(self, user_id):
        """Get user statistics"""
        projects = self.get_user_projects(user_id)
        events = self.get_user_events(user_id)
        contributions = self.calculate_contributions(events)

        total_contributions = sum(contributions.values())
        membership_projects = len(projects)
        activity_projects = distinct_projects_from_events(events, days=365)
        total_projects = max(membership_projects, activity_projects)

        return {
            "total_contributions": total_contributions,
            "total_projects": total_projects,
            "membership_projects": membership_projects,
            "activity_projects": activity_projects,
            "daily_contributions": contributions,
            "events": events[:10],
        }


def distinct_projects_from_events(events, days=365):
    """Count distinct project_id values in the event stream (covers private activity the /projects list can miss)."""
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    ids = set()
    for e in events:
        try:
            raw = e.get("created_at")
            if not raw:
                continue
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt < cutoff:
                continue
        except (TypeError, ValueError):
            continue
        pid = e.get("project_id")
        if pid is not None:
            ids.add(pid)
    return len(ids)


def get_contribution_level(count):
    """Determine contribution level based on count"""
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


def generate_contribution_grid(contributions, days=365):
    """Generate contribution grid for the last `days` calendar days (inclusive of today)."""
    grid = []
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days - 1)
    
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        count = contributions.get(date_str, 0)
        level = get_contribution_level(count)
        grid.append({
            'date': date_str,
            'count': count,
            'level': level,
            'weekday': current_date.weekday()
        })
        current_date += timedelta(days=1)
    
    return grid


def grid_week_columns(grid):
    """Columns used by the same packing rules as the draw loop (advance after each Sunday)."""
    week = 0
    max_col = 0
    for day in grid:
        max_col = max(max_col, week)
        if day["weekday"] == 6:
            week += 1
    return max_col + 1


def generate_svg(stats, width=800, height=200):
    """Generate SVG heatmap (rolling year ending today; month labels above grid)."""
    contributions = stats["daily_contributions"]

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
    svg.append(
        f'  <g transform="translate({margin + 30}, {margin + month_band})">'
    )

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
            f'<title>{day["date"]}: {day["count"]} events</title></rect>'
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

    return "\n".join(svg)

def main():
    """Main function"""
    print(f"Fetching GitLab activity for {GITLAB_USERNAME}...")
    
    fetcher = GitLabActivityFetcher(GITLAB_USERNAME, GITLAB_TOKEN, GITLAB_URL)
    
    # Get user ID
    user_id = fetcher.get_user_id()
    if not user_id:
        print(f"Error: Could not find user '{GITLAB_USERNAME}'")
        sys.exit(1)
    
    print(f"Found user ID: {user_id}")
    
    # Fetch stats
    print("Fetching activity...")
    stats = fetcher.get_stats(user_id)
    
    print(f"Total activity (365d): {stats['total_contributions']} events")
    print(
        f"Projects: {stats['total_projects']} "
        f"(membership API: {stats['membership_projects']}, "
        f"repos with activity: {stats['activity_projects']})"
    )
    # Generate SVG
    print(f"Generating {OUTPUT_FILE}...")
    svg_content = generate_svg(stats)
    
    with open(OUTPUT_FILE, 'w') as f:
        f.write(svg_content)

    print(f"✓ Successfully generated {OUTPUT_FILE}")
    
    # Display recent activity
    if stats['events']:
        print("\nRecent activity:")
        for event in stats['events'][:5]:
            action = event.get('action_name', 'unknown')
            date = event.get('created_at', '')
            print(f"  • {action} - {date}")

if __name__ == '__main__':
    main()
