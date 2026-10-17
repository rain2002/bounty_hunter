import os
import sys
import time
import requests
import smtplib
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sys.stdout.reconfigure(encoding='utf-8')

# Known scraper bots, duplicate mirrors, and low-quality aggregators to ignore
BLACKLIST_REPOS = {
    'zhangjiayang6835-cyber/bounty-plaza',
    'freedom-winds/BountyScout',
    'dev-kp-eloper/BountyScout',
    'Uuriko/project-room',
    'relayhop/bounty-watcher',
    'Ikalus1988/MisakaNet',
    'IncredibleSpacecow/bounty-agent-dryrun',
    'ahmedfuzayl-gif/commit-monitor',
    'thirdshiftworks/opportunity-scanner'
}

BLACKLIST_KEYWORDS = [
    'bountyscout', 'bounty alert:', 'new opportunityies found', 'project-room',
    'bounty-plaza', 'neglect ladder', 'live payout sweep', 'commit-monitor'
]

def get_github_bounties(hours=4):
    """
    Search GitHub for real, funded bounties in the $50-$100 range and Algora/Opire/Polar tags.
    Strips out aggregator spam, forks, and automated bot mirrors.
    """
    print(f"[*] Searching GitHub for verified bounties created in last {hours}h...")
    url = "https://api.github.com/search/issues"
    cutoff_time = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime('%Y-%m-%d')
    
    queries = [
        f'bounty "$50" is:issue state:open created:>={cutoff_time}',
        f'bounty "$100" is:issue state:open created:>={cutoff_time}',
        f'"[Bounty" in:title is:issue state:open created:>={cutoff_time}',
        f'"console.algora.io" is:issue state:open created:>={cutoff_time}',
        f'"app.opire.dev" is:issue state:open created:>={cutoff_time}'
    ]
    
    headers = {'User-Agent': 'BountySniper-v2.0'}
    results = []
    seen_urls = set()
    
    for q in queries:
        try:
            resp = requests.get(url, params={"q": q, "sort": "created", "order": "desc", "per_page": 10}, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", []):
                    html_url = item.get("html_url")
                    if html_url in seen_urls:
                        continue
                        
                    repo = '/'.join(item.get('repository_url', '').split('/')[-2:])
                    title = item.get("title", "")
                    body = item.get("body", "") or ""
                    
                    # Blacklist checks
                    if repo.lower() in [b.lower() for b in BLACKLIST_REPOS]:
                        continue
                    if any(kw in title.lower() or kw in repo.lower() for kw in BLACKLIST_KEYWORDS):
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
    Directly query Superteam Earn API for open development bounties paying in USDC.
    """
    print("[*] Checking Superteam Earn for developer bounties...")
    results = []
    try:
        r = requests.get('https://earn.superteam.fun/api/listings?category=Development', headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                title = item.get('title')
                reward = item.get('rewardAmount')
                token = item.get('token')
                slug = item.get('slug')
                l_type = item.get('type')
                status = item.get('status')
                
                if status == 'OPEN':
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
        
    print("Sending alerts via Gmail...")
    
    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = to_email
    msg['Subject'] = f"🎯 Bounty Sniper: {len(results)} new bounties found!"
    
    body = f"Bounty Sniper found {len(results)} verified bounties!\n\n"
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
    print("=" * 60)
    print(" BOUNTY SNIPER V2.0 (GitHub/Algora + Superteam Earn) ".center(60, "="))
    print("=" * 60)
    
    # Check GitHub (last 4 hours for 3-hour cron, or fallback 24h if manual)
    hours = int(os.environ.get("LOOKBACK_HOURS", "4"))
    github_results = get_github_bounties(hours=hours)
    superteam_results = get_superteam_bounties()
    
    all_results = github_results + superteam_results
    
    # Deduplicate by URL
    seen_urls = set()
    unique_results = []
    for r in all_results:
        if r['url'] not in seen_urls:
            unique_results.append(r)
            seen_urls.add(r['url'])
            
    if not unique_results:
        print("\nNo new bounties found in the current window.")
    else:
        print(f"\n🎯 Found {len(unique_results)} verified bounties:\n")
        for res in unique_results:
            print(f"[{res['source']}] {res['title']}")
            print(f"Link: {res['url']}\n")
            
        # Send Email Alert if configured
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
        to_email = os.environ.get("TO_EMAIL")
        
        if gmail_user and gmail_pass and to_email:
            send_email_alert(unique_results, gmail_user, gmail_pass, to_email)
        else:
            print("(Email notification credentials not set; outputting to terminal.)")

if __name__ == "__main__":
    main()
