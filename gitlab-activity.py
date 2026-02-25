#!/usr/bin/env python3
"""
GitLab Activity Tracker
Fetches GitLab contributions and generates an SVG visualization
"""

import requests
import json
from datetime import datetime, timedelta
from collections import defaultdict
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
        """Fetch user's projects"""
        try:
            # Use /projects?membership=true to get all projects the user is a member of
            url = f"{self.api_url}/projects" if self.token else f"{self.api_url}/users/{user_id}/projects"
            params = {'per_page': 100}
            if self.token:
                params['membership'] = 'true'
                
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
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
        total_projects = len(projects)
        
        return {
            'total_contributions': total_contributions,
            'total_projects': total_projects,
            'daily_contributions': contributions,
            'events': events[:10]  # Latest 10 events
        }

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

def generate_contribution_grid(contributions, weeks=52):
    """Generate contribution grid for the last N weeks"""
    grid = []
    end_date = datetime.now().date()
    start_date = end_date - timedelta(weeks=weeks)
    
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

def generate_svg(stats, width=800, height=200):
    """Generate SVG visualization"""
    contributions = stats['daily_contributions']
    total = stats['total_contributions']
    projects = stats['total_projects']
    
    grid = generate_contribution_grid(contributions)
    
    # SVG parameters
    cell_size = 10
    cell_gap = 3
    margin = 20
    header_height = 60
    
    # Calculate dimensions
    weeks = 52
    days = 7
    grid_width = weeks * (cell_size + cell_gap)
    grid_height = days * (cell_size + cell_gap)
    
    svg_width = grid_width + 2 * margin + 100
    svg_height = grid_height + 2 * margin + header_height
    
    # Start SVG
    svg = [
        f'<svg width="{svg_width}" height="{svg_height}" xmlns="http://www.w3.org/2000/svg">',
        f'  <rect width="{svg_width}" height="{svg_height}" fill="{COLORS["background"]}" rx="6"/>',
        '',
        '  <!-- Title -->',
        f'  <text x="{margin}" y="{margin + 20}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="18" font-weight="bold">',
        f'    GitLab Contributions',
        '  </text>',
        '',
        '  <!-- Stats -->',
        f'  <text x="{margin}" y="{margin + 45}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="12">',
        f'    Total: {total} contributions in the last year',
        '  </text>',
        '',
        '  <!-- Contribution Grid -->',
        f'  <g transform="translate({margin + 30}, {margin + header_height})">',
    ]
    
    # Draw day labels
    days_labels = ['Mon', 'Wed', 'Fri']
    for i, label in enumerate([1, 3, 5]):
        y = label * (cell_size + cell_gap)
        svg.append(f'    <text x="-25" y="{y + cell_size}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="9">{days_labels[i]}</text>')
    
    # Draw contribution cells
    week = 0
    week_day = grid[0]['weekday']
    
    for i, day in enumerate(grid):
        x = week * (cell_size + cell_gap)
        y = day['weekday'] * (cell_size + cell_gap)
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
    
    return '\n'.join(svg)

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
    print("Fetching contributions...")
    stats = fetcher.get_stats(user_id)
    
    print(f"Total contributions: {stats['total_contributions']}")
    print(f"Total projects: {stats['total_projects']}")
    
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
