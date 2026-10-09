import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json
import time

from datetime import datetime, timedelta

def get_github_bounties():
    print("Searching GitHub for bounties...")
    url = "https://api.github.com/search/issues"
    
    # Only look for bounties created in the last 4 hours (since the script runs every 3 hours)
    cutoff_time = (datetime.utcnow() - timedelta(hours=4)).strftime('%Y-%m-%dT%H:%M:%S')
    
    queries = [
        f"label:bounty state:open language:python created:>={cutoff_time}",
        f"label:bounty state:open language:javascript created:>={cutoff_time}",
        f"label:paid state:open language:python created:>={cutoff_time}",
        f"label:paid state:open language:javascript created:>={cutoff_time}"
    ]
    
    results = []
    for q in queries:
        try:
            resp = requests.get(url, params={"q": q, "sort": "created", "order": "desc"})
            if resp.status_code == 200:
                data = resp.json()
                for item in data.get("items", [])[:5]:
                    results.append({
                        "source": "GitHub",
                        "title": item.get("title"),
                        "url": item.get("html_url")
                    })
            time.sleep(1) # Be nice to the API
        except Exception as e:
            print(f"Error fetching GitHub: {e}")
            
    return results

def get_reddit_jobs():
    print("Searching Reddit for jobs...")
    headers = {'User-agent': 'BountySniper 1.0'}
    subreddits = "slavelabour+forhire"
    url = f"https://www.reddit.com/r/{subreddits}/new.json"
    
    results = []
    keywords = ["script", "python", "scrape"]
    
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            for child in data.get("data", {}).get("children", [])[:20]:
                post = child.get("data", {})
                title = post.get("title", "").lower()
                body = post.get("selftext", "").lower()
                created_utc = post.get("created_utc", 0)
                
                # Check if it was created in the last 4 hours
                cutoff_timestamp = (datetime.utcnow() - timedelta(hours=4)).timestamp()
                
                if created_utc >= cutoff_timestamp and any(kw in title or kw in body for kw in keywords):
                    results.append({
                        "source": f"Reddit (r/{post.get('subreddit')})",
                        "title": post.get("title"),
                        "url": f"https://www.reddit.com{post.get('permalink')}"
                    })
    except Exception as e:
        print(f"Error fetching Reddit: {e}")
        
    return results

import os

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_email_alert(results, user, password, to_email):
    if not user or not password or not to_email:
        return
        
    print("Sending alerts via Gmail...")
    
    msg = MIMEMultipart()
    msg['From'] = user
    msg['To'] = to_email
    msg['Subject'] = f"🎯 Bounty Sniper: {len(results)} new bounties!"
    
    body = f"Bounty Sniper found {len(results)} potential bounties!\n\n"
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
    print("=" * 50)
    print(" BOUNTY SNIPER V1.0 ".center(50, "="))
    print("=" * 50)
    
    github_results = get_github_bounties()
    reddit_results = get_reddit_jobs()
    
    # Deduplicate by URL
    all_results = github_results + reddit_results
    seen_urls = set()
    unique_results = []
    for r in all_results:
        if r['url'] not in seen_urls:
            unique_results.append(r)
            seen_urls.add(r['url'])
    
    if not unique_results:
        print("No new bounties found right now.")
    else:
        print(f"\nFound {len(unique_results)} potential bounties:\n")
        for res in unique_results:
            print(f"[{res['source']}] {res['title']}")
            print(f"Link: {res['url']}\n")
            
        # Send Email Alert
        gmail_user = os.environ.get("GMAIL_USER")
        gmail_pass = os.environ.get("GMAIL_APP_PASSWORD")
        to_email = os.environ.get("TO_EMAIL")
        
        if gmail_user and gmail_pass and to_email:
            send_email_alert(unique_results, gmail_user, gmail_pass, to_email)
        else:
            print("\n(To enable email alerts, set GMAIL_USER, GMAIL_APP_PASSWORD, and TO_EMAIL environment variables.)")

if __name__ == "__main__":
    main()
