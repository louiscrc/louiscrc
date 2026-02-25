import os
import sys
import requests
from datetime import datetime, timedelta

GITHUB_TOKEN = os.getenv('GH_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME', 'louiscrc')

if not GITHUB_TOKEN:
    print("Error: GH_TOKEN is required for fetching GitHub stats.")
    sys.exit(1)

query = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
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
    "Content-Type": "application/json"
}

response = requests.post(
    "https://api.github.com/graphql",
    json={"query": query, "variables": {"login": GITHUB_USERNAME}},
    headers=headers
)

if response.status_code != 200:
    print(f"Error fetching GitHub stats: {response.text}")
    sys.exit(1)

data = response.json()
if 'errors' in data:
    print(f"GraphQL Error: {data['errors']}")
    sys.exit(1)

calendar = data['data']['user']['contributionsCollection']['contributionCalendar']
total_contributions = calendar['totalContributions']
weeks = calendar['weeks']

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

# SVG parameters
cell_size = 10
cell_gap = 3
margin = 20
header_height = 60

# Calculate dimensions
total_weeks = len(weeks)
days = 7
grid_width = total_weeks * (cell_size + cell_gap)
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
    f'    GitHub Contributions',
    '  </text>',
    '',
    '  <!-- Stats -->',
    f'  <text x="{margin}" y="{margin + 45}" fill="{COLORS["text"]}" font-family="Arial, sans-serif" font-size="12">',
    f'    Total: {total_contributions} contributions in the last year',
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
# Find the start week offset based on the first day
first_day = grid[0]
week = 0

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

with open("github-stats.svg", "w") as f:
    f.write('\n'.join(svg))
print("Successfully generated github-stats.svg")