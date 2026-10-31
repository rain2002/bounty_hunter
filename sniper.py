import os
import sys
import time
import requests
import smtplib
import json
import re
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.stdout.reconfigure(encoding='utf-8')

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen_bounties.json")

def load_seen_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
    return {}

def save_seen_history(history):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"Error saving seen history: {e}")

# Known scraper bots, duplicate mirrors, fake forks, and low-quality aggregators to ignore
BLACKLIST_USERS = {
    'furongjun-1999', 'paraloom-labs', 'limitlessprojects', 'micahheneveld',
    'dseelinger', 'djbrl', 'useverdex', 'facesnatcher56-star', 'stxtxm',
    'vandelay87', 'ariahendrawan-sudo', 'zhangjiayang6835-cyber', 'freedom-winds',
    'dev-kp-eloper', 'uuriko', 'relayhop', 'ikalus1988', 'ahmedfuzayl-gif',
    'thirdshiftworks', 'incrediblespacecow', 'bounty-watcher', 'bounty-plaza',
    'gospelsam019', 'neatlogs', 'xaviercallens', 'teslims2', 'axalnetwork',
    'myzubster-ecosystem', 'credenceorg', 'dmavs412', '96loveslife',
    'neziahtech', 'riteshekbote', 'auscaster', 'rroland10', 'guyue-arch',
    'huynhnhatquandongnai-source', 'dragonire9', 'airdropia', 'taxueseek', 'litang9', 'secopsnews', 'roam-game-org', 'securebananalabs', 'era-projects', 'xhtoken', 'openobserve', 'paraspell', 'aomediacodec', 'basedhardware', 'zigzagboi1', 'sybil-solutions', 'tenstorrent', 'dotnet', 'riteshbonthalakoti', 'ruohong2018', 'chainreactors', 'brucefeiix', 'tyaoo', 'faisalkindi', 'swu-karabast', 'windy10v10ai', 'agenta-ai', 'mautic', 'alfrexo95', 'rohank143'
}

BLACKLIST_TITLE_KEYWORDS = [
    'bountyscout', 'bounty scout', 'bounty alert', 'project-room',
    'bounty-plaza', 'neglect ladder', 'live payout sweep', 'commit-monitor',
    'frame', 'frames', 'label from scratch', 'proc passive', 'companion',
    'elite dangerous', 'journal', 'review & fix log', 'prototype v5',
    'scoped task', 'unaccounted', 'points', 'trading competition',
    'audit grant', 'audit grants', 'gameplay', 'combat milestones',
    'intake', '[intake', '测评报告', '测评', '体验快测', '增量测评',
    'radar', 'monetization-runtime', 's1 handoff', 'handoff', 'coordinator state',
    'cve disclosure', 'security.md', 'bug bounty scope', 'bounty-escrow',
    'proposal for @', '$hive', 'hivemind', 'claim your bounty spot',
    'proposal', 'proposed', 'bounty proposal', 'outbound link', 'link report',
    'broken link', 'dsh-', 'dsh_', 'big_model_radar', 'security advisory', 'advisory cve', 'vulnerability', 'gssoc', '每日信息流', '每日安全资讯', 'picker', 'bounty hunter', 'digest', 'feed', 'cve-'
]

repo_star_cache = {}

def get_repo_stars(repo_full_name, headers):
    if repo_full_name in repo_star_cache:
        return repo_star_cache[repo_full_name]
    try:
        r = requests.get(f'https://api.github.com/repos/{repo_full_name}', headers=headers, timeout=5)
        if r.status_code == 200:
            stars = r.json().get('stargazers_count', 0)
            repo_star_cache[repo_full_name] = stars
            return stars
    except Exception:
        pass
    repo_star_cache[repo_full_name] = 0
    return 0

CASH_TITLE_REGEX = re.compile(r'\[\s*(?:bounty\s*)?\$[0-9]{2,5}\s*\]|\b(?:bounty\s*:\s*\$[0-9]{2,5})\b', re.IGNORECASE)

def is_valid_github_bounty(item, headers):
    repo = '/'.join(item.get('repository_url', '').split('/')[-2:])
    owner = repo.split('/')[0].lower() if '/' in repo else ''
    author = (item.get('user') or {}).get('login', '').lower()
    raw_title = item.get('title', '')
    title_lower = raw_title.lower()
    body = (item.get('body') or '').lower()

    # 1. Filter blacklisted user accounts & bot mirrors (owner or issue author)
    if owner in BLACKLIST_USERS:
        return False, f"Blacklisted owner: {owner}"
    if author in BLACKLIST_USERS:
        return False, f"Blacklisted author: {author}"

    # 2. Filter blacklisted keywords in title (proposals, reports, junk, news streams)
    if any(kw in title_lower for kw in BLACKLIST_TITLE_KEYWORDS):
        return False, "Blacklisted keyword in title"

    # 3. Filter non-cash 'points' or unverified token rewards
    if 'points' in body or '$hive' in body or '$hive' in title_lower:
        return False, "Non-cash points/unlisted token reward"

    # 4. Check for verified bot indicators (Algora, Polar, Opire)
    has_escrow_bot = (
        'console.algora.io/challenges/' in body or
        'algora[bot]' in body or
        'algora-io' in body or
        ('polar.sh/' in body and any(k in body for k in ['pledge', 'reward', 'polar[bot]', 'polar-sh'])) or
        ('app.opire.dev/' in body and any(k in body for k in ['bounty', 'opire[bot]']))
    )

    # 5. Explicit cash bounty tag verification (e.g. "[$50]", "[$100]", "[Bounty $250]")
    has_cash_title = bool(CASH_TITLE_REGEX.search(raw_title))

    # Strict Gate: Must have verified escrow bot OR an explicit cash bounty tag
    if not has_escrow_bot and not has_cash_title:
        return False, "No verified escrow bot or explicit [$XX] cash bounty tag"

    # 6. Quality gate: repository must have >= 20 stars (unless verified escrow bot is present)
    stars = get_repo_stars(repo, headers)
    if stars < 20 and not has_escrow_bot:
        return False, f"Unverified repo ({stars} stars)"

    return True, f"Verified cash bounty ({stars} stars)"

def get_github_bounties(hours=4):
    """
    Search GitHub for real, funded bounties in the $50-$200 range with strict legitimacy filters.
    """
    print(f"[*] Searching GitHub for verified bounties (lookback: {hours}h)...")
    url = "https://api.github.com/search/issues"
    cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%d')
    
    # Target actual cash bounties and escrow platforms
    queries = [
        f'label:bounty state:open created:>={cutoff_time}',
        f'label:paid state:open created:>={cutoff_time}',
        f'label:reward state:open created:>={cutoff_time}',
        f'"[bounty" in:title is:issue state:open created:>={cutoff_time}',
        f'"app.opire.dev" is:issue state:open created:>={cutoff_time}'
    ]
    
    headers = {'User-Agent': 'BountySniper-v2.5'}
    gh_token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if gh_token:
        headers['Authorization'] = f'token {gh_token}'

    results = []
    seen_urls = set()
    
    for q in queries:
        try:
            resp = requests.get(url, params={"q": q, "sort": "created", "order": "desc", "per_page": 15}, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    html_url = item.get("html_url")
                    if html_url in seen_urls:
                        continue
                        
                    repo = '/'.join(item.get('repository_url', '').split('/')[-2:])
                    title = item.get("title", "")
                    
                    is_valid, reason = is_valid_github_bounty(item, headers)
                    if not is_valid:
                        continue
                        
                    seen_urls.add(html_url)
                    results.append({
                        "source": f"GitHub ({repo})",
                        "title": title,
                        "url": html_url,
                        "comments": item.get("comments", 0),
                        "created_at": item.get("created_at")
                    })
            time.sleep(1) # Rate limit respect
        except Exception as e:
            print(f"Error fetching GitHub query '{q}': {e}")
            
    return results

def get_superteam_bounties():
    """
    Query Superteam Earn API for open, $0-upfront cash development and content bounties.
    Filters out audit discount grants, trading competitions, and regional-restricted tracks.
    """
    print("[*] Checking Superteam Earn for verified cash bounties ($0 upfront)...")
    results = []
    try:
        r = requests.get('https://earn.superteam.fun/api/listings', headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                title = item.get('title') or ''
                reward = item.get('rewardAmount')
                token = item.get('token')
                slug = item.get('slug')
                l_type = item.get('type') or 'bounty'
                status = item.get('status')
                desc = (item.get('description') or '').lower()
                title_lower = title.lower()

                if status != 'OPEN':
                    continue

                # 1. Skip non-cash audit service discount grants
                if any(k in title_lower for k in ['audit grant', 'audit discount', 'colosseum projects: up to']):
                    continue

                # 2. Skip regional-only in-person hackathons and language-specific events
                if any(reg in title_lower for reg in [
                    'poland track', 'brazil special', 'balkan', 'madrid', 'turkey', 'rumbo a', 'el encuentro', 'madrid'
                ]):
                    continue

                # 3. Skip bounties requiring user investment, trading, or market creation
                if any(cost_kw in title_lower for cost_kw in [
                    'trading competition', 'trade on', 'create a market', 'panta x', 'test trade', 'deposit'
                ]):
                    continue

                # 4. Skip founder-only support calls, travel grants, and referral schemes
                if any(skip_kw in title_lower for skip_kw in [
                    'founder support', 'travel boost', 'bring your friends', 'referral', 'fair launch'
                ]):
                    continue

                results.append({
                    "source": "Superteam Earn",
                    "title": f"[{reward} {token}] {title}",
                    "url": f"https://earn.superteam.fun/listings/{l_type}/{slug}",
                    "comments": 0,
                    "created_at": item.get('deadline')
                })
    except Exception as e:
        print(f"Error querying Superteam Earn: {e}")
        
    return results

def send_email_alert(results, user, password, to_email):
    if not user or not password or not to_email:
        return
        
    print("Sending verified alerts via Gmail...")
    
    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = to_email
    msg['Subject'] = f"🎯 Bounty Sniper: {len(results)} verified bounties found!"
    
    body = f"Bounty Sniper found {len(results)} verified bounties (filtered for real cash & legitimate repos)!\n\n"
    for res in results:
        body += f"[{res['source']}] {res['title']}\n{res['url']}\n\n"
        
    msg.attach(MIMEText(body, 'plain', 'utf-8'))
    
    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
        server.quit()
        print("Email alert sent successfully.")
    except Exception as e:
        print(f"Error sending email: {e}")

def main():
    print("=" * 65)
    print(" BOUNTY SNIPER V2.6 (Persistent Anti-Duplication Engine) ".center(65, "="))
    print("=" * 65)
    
    # Handle optional command-line flags
    if "--reset" in sys.argv:
        if os.path.exists(HISTORY_FILE):
            os.remove(HISTORY_FILE)
            print("[*] History file reset successfully.")

    show_all = "--all" in sys.argv
    seen_history = load_seen_history()
    print(f"[*] Loaded {len(seen_history)} previously tracked bounties from history.")

    hours = int(os.environ.get("LOOKBACK_HOURS", "12"))
    github_results = get_github_bounties(hours=hours)
    superteam_results = get_superteam_bounties()
    
    all_results = github_results + superteam_results
    
    # Filter out duplicates and already-seen bounties
    run_seen = set()
    new_results = []
    
    for r in all_results:
        url = r['url']
        if url in run_seen:
            continue
        run_seen.add(url)

        if not show_all and url in seen_history:
            continue
            
        new_results.append(r)
            
    if not new_results:
        print(f"\nClean sweep: No new bounties found since last run ({len(seen_history)} already tracked).")
    else:
        print(f"\n🎯 Found {len(new_results)} NEW verified bounties:\n")
        now_str = datetime.now(timezone.utc).isoformat()
        for res in new_results:
            print(f"[{res['source']}] {res['title']}")
            print(f"Link: {res['url']}\n")
            seen_history[res['url']] = {
                "source": res['source'],
                "title": res['title'],
                "first_seen": now_str
            }
            
        save_seen_history(seen_history)
            
        # Send Email Alert for NEW findings only
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
        to_email = os.environ.get("TO_EMAIL")
        
        if gmail_user and gmail_pass and to_email:
            send_email_alert(new_results, gmail_user, gmail_pass, to_email)
        else:
            print("(Email notification credentials not set; outputting to terminal.)")

if __name__ == "__main__":
    main()
