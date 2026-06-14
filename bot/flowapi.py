from curl_cffi import requests
import re
import sys
import json

def get_flowvideo_links(target_url: str):
    try:
        session = requests.Session(impersonate="chrome120")

        # 1. Fetch main page to get tokens
        resp = session.get("https://flowvideoplayer.com/")
        if resp.status_code != 200:
            return {"error": f"Failed to access cookies: {resp.status_code}"}

        html = resp.text

        token_match = re.search(r'<meta name="csrf-token" content="([^"]+)">', html)
        if not token_match:
            return {"error": "Failed to find csrf-token in page source"}

        csrf_token = token_match.group(1)

        # 2. Make the API request
        api_url = "https://flowvideoplayer.com/telegram/bot/search/video"
        headers = {
            "Content-Type": "application/json",
            "X-CSRF-TOKEN": csrf_token,
            "Origin": "https://flowvideoplayer.com",
            "Referer": "https://flowvideoplayer.com/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin"
        }

        payload = {"url": target_url}
        api_resp = session.post(api_url, headers=headers, json=payload)

        if api_resp.status_code != 200:
             return {"error": f"API returned status {api_resp.status_code}"}

        data = api_resp.json()
        return data

    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "No URL provided"}))
        sys.exit(1)

    url = sys.argv[1]
    result = get_flowvideo_links(url)
    print(json.dumps(result))
