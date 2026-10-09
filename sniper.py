import sys
sys.stdout.reconfigure(encoding='utf-8')
import requests
import json
import time

def get_github_bounties():
    print("Searching GitHub for bounties...")
    url = "https://api.github.com/search/issues"
    
    queries = [
        "label:bounty state:open language:python",
        "label:bounty state:open language:javascript",
        "label:paid state:open language:python",
        "label:paid state:open language:javascript"
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
                
                if any(kw in title or kw in body for kw in keywords):
                    results.append({
                        "source": f"Reddit (r/{post.get('subreddit')})",
                        "title": post.get("title"),
                        "url": f"https://www.reddit.com{post.get('permalink')}"
                    })
    except Exception as e:
        print(f"Error fetching Reddit: {e}")
        
    return results

import os

def send_discord_alert(results, webhook_url):
    if not webhook_url:
        return
        
    print("Sending alerts to Discord...")
    message = f"🎯 **Bounty Sniper found {len(results)} potential bounties!**\n\n"
    
    for res in results[:10]: # Limit to 10 to avoid Discord message length limits
        message += f"**[{res['source']}]** {res['title']}\n<{res['url']}>\n\n"
        
    if len(results) > 10:
        message += f"...and {len(results) - 10} more!"
        
    try:
        resp = requests.post(webhook_url, json={"content": message})
        if resp.status_code == 204:
            print("Discord alert sent successfully.")
        else:
            print(f"Failed to send Discord alert: {resp.status_code}")
    except Exception as e:
        print(f"Error sending to Discord: {e}")

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
            
        # Send Discord Alert
        webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
        if webhook_url:
            send_discord_alert(unique_results, webhook_url)
        else:
            print("\n(To enable Discord alerts, set the DISCORD_WEBHOOK_URL environment variable.)")

if __name__ == "__main__":
    main()
