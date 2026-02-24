import os
import sys
import requests
import json

GITHUB_TOKEN = os.getenv('GH_TOKEN')
GITHUB_USERNAME = os.getenv('GITHUB_USERNAME', 'louiscrc')

if not GITHUB_TOKEN:
    print("Error: GH_TOKEN is required for fetching GitHub stats.")
    sys.exit(1)

# GraphQL query to get user stats
query = """
query($login: String!) {
  user(login: $login) {
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      restrictedContributionsCount
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      nodes {
        stargazerCount
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

user_data = data['data']['user']
contribs = user_data['contributionsCollection']

total_commits = contribs['totalCommitContributions'] + contribs.get('restrictedContributionsCount', 0)
total_prs = contribs['totalPullRequestContributions']
total_issues = contribs['totalIssueContributions']

stars = sum(repo['stargazerCount'] for repo in user_data['repositories']['nodes'])

# Generate SVG
COLORS = {
    'background': '#0d1117',
    'border': '#30363d',
    'text': '#c9d1d9',
    'accent': '#58a6ff',
    'icon': '#7ee787'
}

svg = f"""<svg width="400" height="180" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title {{ font: bold 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {COLORS['accent']}; }}
    .stat {{ font: 600 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif; fill: {COLORS['text']}; }}
    .stricon {{ font: 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif; fill: {COLORS['icon']}; }}
    .bold {{ font-weight: 700; }}
  </style>
  <rect width="400" height="180" fill="{COLORS['background']}" rx="8" stroke="{COLORS['border']}" stroke-width="1"/>
  <text x="25" y="35" class="title">GitHub Stats</text>
  
  <g transform="translate(25, 75)">
    <text x="0" y="0" class="stricon">⭐</text>
    <text x="25" y="0" class="stat">Total Stars Earned:</text>
    <text x="350" y="0" class="stat bold" text-anchor="end">{stars}</text>
  </g>
  
  <g transform="translate(25, 110)">
    <text x="0" y="0" class="stricon">🔄</text>
    <text x="25" y="0" class="stat">Total Commits (This Year):</text>
    <text x="350" y="0" class="stat bold" text-anchor="end">{total_commits}</text>
  </g>
  
  <g transform="translate(25, 145)">
    <text x="0" y="0" class="stricon">🔀</text>
    <text x="25" y="0" class="stat">Total PRs &amp; Issues:</text>
    <text x="350" y="0" class="stat bold" text-anchor="end">{total_prs + total_issues}</text>
  </g>
</svg>"""

with open("github-stats.svg", "w") as f:
    f.write(svg)
print("Successfully generated github-stats.svg")
