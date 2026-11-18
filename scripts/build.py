"""Rebuild README.md and the stats SVGs from live GitHub data.

Needs GITHUB_TOKEN in the environment. Standard library only.
"""

import html
import json
import os
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

USER = "harshil-sri"
REPO = f"{USER}/{USER}"
ENDORSE_LABEL = "endorse"
SKIP_RECENT = {USER}
SKIP_LANGUAGES = {"HTML", "CSS", "SCSS"}
ROOT = Path(__file__).resolve().parent.parent
TOKEN = os.environ["GITHUB_TOKEN"]
NOW = datetime.now(timezone.utc)


def request(url, body=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-readme-builder",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def graphql(query, **variables):
    data = request("https://api.github.com/graphql", {"query": query, "variables": variables})
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def ago(iso):
    seconds = (NOW - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds()
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if seconds >= size:
            n = int(seconds // size)
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return "just now"


PROFILE_QUERY = """
query($login: String!) {
  user(login: $login) {
    createdAt
    followers { totalCount }
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      restrictedContributionsCount
      contributionCalendar { totalContributions }
    }
    owned: repositories(first: 100, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
    recent: repositories(first: 8, orderBy: {field: PUSHED_AT, direction: DESC},
                         privacy: PUBLIC, ownerAffiliations: [OWNER, COLLABORATOR]) {
      nodes {
        name
        nameWithOwner
        url
        description
        pushedAt
        defaultBranchRef {
          target { ... on Commit { messageHeadline committedDate } }
        }
      }
    }
  }
}
"""


def recent_section(user):
    items = []
    for repo in user["recent"]["nodes"]:
        if repo["name"] in SKIP_RECENT:
            continue
        commit = (repo.get("defaultBranchRef") or {}).get("target") or {}
        items.append((commit.get("committedDate") or repo["pushedAt"], repo, commit))
    items.sort(key=lambda item: item[0], reverse=True)
    rows = []
    for when, repo, commit in items[:4]:
        message = html.escape(commit.get("messageHeadline", ""))[:80]
        rows.append(f"- **[{repo['nameWithOwner']}]({repo['url']})**: {message} <sub>({ago(when)})</sub>")
    return "\n".join(rows) if rows else "_Nothing public pushed recently._"


def endorsements_section():
    issues = request(
        f"https://api.github.com/repos/{REPO}/issues?labels={ENDORSE_LABEL}&state=open&per_page=50"
    )
    lines = []
    for issue in sorted(issues, key=lambda i: i["number"]):
        skill = issue["title"].split(":", 1)[-1].strip()
        reactions = request(f"{issue['url']}/reactions?content=%2B1&per_page=100")
        seen, avatars = set(), []
        for r in reactions:
            login = r["user"]["login"]
            if login in seen or login == USER:
                continue
            seen.add(login)
            avatars.append(
                f'<a href="https://github.com/{login}"><img src="{r["user"]["avatar_url"]}&s=40" '
                f'width="20" height="20" alt="{login}" title="{login}" /></a>'
            )
        count = f" <sub>{len(avatars)}</sub>" if avatars else ""
        lines.append(f"- [{html.escape(skill)}]({issue['html_url']}){count} {''.join(avatars)}".rstrip())
    return "\n".join(lines) if lines else "_No skills listed yet._"


def badges(name):
    base = "https://img.shields.io/github"
    q = "style=flat-square&labelColor=343b41"
    return (
        f'<img alt="stars" src="{base}/stars/{USER}/{name}?{q}&label=%E2%98%85" /> '
        f'<img alt="last commit" src="{base}/last-commit/{USER}/{name}?{q}&label=updated" />'
    )


SVG_STYLE = """
<style>
  .bg { fill: #ffffff; stroke: #d0d7de; }
  .title { font: 600 15px 'Segoe UI', Ubuntu, sans-serif; fill: #0969da; }
  .label { font: 400 13px 'Segoe UI', Ubuntu, sans-serif; fill: #57606a; }
  .value { font: 600 13px 'Segoe UI', Ubuntu, sans-serif; fill: #1f2328; }
  .track { fill: #eaeef2; }
  @media (prefers-color-scheme: dark) {
    .bg { fill: #0d1117; stroke: #30363d; }
    .title { fill: #58a6ff; }
    .label { fill: #8b949e; }
    .value { fill: #e6edf3; }
    .track { fill: #21262d; }
  }
  .row { opacity: 0; animation: fade 0.5s ease-out forwards; }
  .bar { transform-box: fill-box; transform: scaleX(0); animation: grow 0.9s ease-out forwards; }
  @keyframes fade { to { opacity: 1; } }
  @keyframes grow { to { transform: scaleX(1); } }
</style>
"""

WIDTH, HEIGHT = 420, 200


def svg_frame(title, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{html.escape(title)}">{SVG_STYLE}'
        f'<rect class="bg" x="0.5" y="0.5" rx="8" width="{WIDTH - 1}" height="{HEIGHT - 1}"/>'
        f'<text class="title" x="22" y="34">{html.escape(title)}</text>{body}</svg>'
    )


def overview_svg(user):
    c = user["contributionsCollection"]
    stars = sum(r["stargazerCount"] for r in user["owned"]["nodes"])
    rows = [
        ("Contributions in the last year", c["contributionCalendar"]["totalContributions"]),
        ("Commits (public)", c["totalCommitContributions"]),
        ("Private contributions", c["restrictedContributionsCount"]),
        ("Pull requests", c["totalPullRequestContributions"]),
        ("Public repos", user["owned"]["totalCount"]),
        ("Stars earned", stars),
    ]
    rows = [(label, value) for label, value in rows if value or label != "Private contributions"]
    body = ""
    for i, (label, value) in enumerate(rows):
        y = 64 + i * 22
        body += (
            f'<g class="row" style="animation-delay:{0.1 + i * 0.12:.2f}s">'
            f'<text class="label" x="22" y="{y}">{label}</text>'
            f'<text class="value" x="{WIDTH - 22}" y="{y}" text-anchor="end">{value:,}</text></g>'
        )
    return svg_frame("Activity", body)


def languages_svg(user):
    totals, colors = defaultdict(int), {}
    for repo in user["owned"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name in SKIP_LANGUAGES:
                continue
            totals[name] += edge["size"]
            colors[name] = edge["node"]["color"] or "#8b949e"
    grand = sum(totals.values()) or 1
    ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)
    top = [kv for kv in ranked if kv[1] / grand >= 0.005][:6]
    bar_x, bar_w = 130, WIDTH - 130 - 70
    body = ""
    for i, (name, size) in enumerate(top):
        y = 64 + i * 22
        pct = size / grand
        body += (
            f'<g class="row" style="animation-delay:{0.1 + i * 0.12:.2f}s">'
            f'<text class="label" x="22" y="{y}">{html.escape(name)}</text>'
            f'<rect class="track" x="{bar_x}" y="{y - 9}" width="{bar_w}" height="8" rx="4"/>'
            f'<rect class="bar" style="animation-delay:{0.2 + i * 0.12:.2f}s" x="{bar_x}" y="{y - 9}" '
            f'width="{max(bar_w * pct, 4):.1f}" height="8" rx="4" fill="{colors[name]}"/>'
            f'<text class="value" x="{WIDTH - 22}" y="{y}" text-anchor="end">{pct:.0%}</text></g>'
        )
    return svg_frame("Languages (public repos)", body)


def main():
    user = graphql(PROFILE_QUERY, login=USER)["user"]
    out = ROOT / "generated"
    out.mkdir(exist_ok=True)
    (out / "overview.svg").write_text(overview_svg(user), encoding="utf-8")
    (out / "languages.svg").write_text(languages_svg(user), encoding="utf-8")

    text = (ROOT / "templates" / "README.tpl.md").read_text(encoding="utf-8")
    ist = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
    replacements = {
        "{{recent}}": recent_section(user),
        "{{endorsements}}": endorsements_section(),
        "{{updated}}": ist.strftime("%d %b %Y, %H:%M IST"),
    }
    for key, value in replacements.items():
        text = text.replace(key, value)
    while "{{badges:" in text:
        start = text.index("{{badges:")
        end = text.index("}}", start)
        text = text[:start] + badges(text[start + 9:end]) + text[end + 2:]
    (ROOT / "README.md").write_text(text, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
