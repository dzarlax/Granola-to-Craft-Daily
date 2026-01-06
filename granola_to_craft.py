import os
import requests
import json
import re
from datetime import datetime, date, timedelta
from dotenv import load_dotenv
from bs4 import BeautifulSoup

# Load environment variables
load_dotenv()

GRANOLA_COOKIE = os.getenv("GRANOLA_COOKIE")
CRAFT_TOKEN = os.getenv("CRAFT_TOKEN")
CRAFT_SPACE_ID = os.getenv("CRAFT_SPACE_ID")
X_DEVICE_ID = os.getenv("X_GRANOLA_DEVICE_ID")
X_WORKSPACE_ID = os.getenv("X_GRANOLA_WORKSPACE_ID")
X_VERSION = os.getenv("X_CLIENT_VERSION") or "6.462.1"

# Craft.do API endpoint
CRAFT_API_BASE = f"https://connect.craft.do/links/{CRAFT_SPACE_ID}/api/v1"

def get_headers():
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Granola-Device-Id": X_DEVICE_ID,
        "X-Granola-Workspace-Id": X_WORKSPACE_ID,
        "X-Client-Version": X_VERSION,
    }
    if GRANOLA_COOKIE.startswith("Bearer "):
        headers["Authorization"] = GRANOLA_COOKIE
    else:
        headers["Cookie"] = GRANOLA_COOKIE
    return headers

def get_granola_documents():
    """Fetches list of all documents (meetings)."""
    url = "https://api.granola.ai/v1/get-documents"
    try:
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching documents: {e}")
        return []

def get_document_panels(doc_id):
    """Fetches the AI panels (Summary, etc.) for a specific document."""
    url = "https://api.granola.ai/v1/get-document-panels"
    try:
        response = requests.post(url, headers=get_headers(), json={"document_id": doc_id})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching panels for {doc_id}: {e}")
        return []

def get_document_transcript(doc_id):
    """Fetches the full transcript for a specific document."""
    url = "https://api.granola.ai/v1/get-document-transcript"
    try:
        response = requests.post(url, headers=get_headers(), json={"document_id": doc_id})
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching transcript for {doc_id}: {e}")
        return []

def html_to_markdown(html_content):
    """Simple conversion of Granola's HTML to Markdown."""
    if not html_content:
        return ""
    soup = BeautifulSoup(html_content, 'html.parser')
    for h3 in soup.find_all('h3'):
        h3.replace_with(f"### {h3.get_text()}\n")
    for li in soup.find_all('li'):
        li.replace_with(f"- {li.get_text()}\n")
    for p in soup.find_all('p'):
        p.replace_with(f"{p.get_text()}\n\n")
    for a in soup.find_all('a'):
        a.replace_with(f"[{a.get_text()}]({a.get('href')})")
    text = soup.get_text()
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def format_transcript(segments):
    """Formats transcript segments into a readable text block."""
    if not segments:
        return "No transcript available."
    
    formatted = ""
    for seg in segments:
        text = seg.get("text", "").strip()
        if text:
            source = seg.get("source", "unknown")
            prefix = "🎙️ " if source == "microphone" else "💻 "
            formatted += f"{prefix}{text}\n\n"
    return formatted.strip()

def filter_meetings_by_date(documents, target_date):
    """Filters documents created on a specific date."""
    date_str = target_date.isoformat()
    return [d for d in documents if d.get("created_at", "").startswith(date_str)]

def send_blocks_to_craft(blocks, target_date_str):
    """Sends structured blocks to Craft.do Daily Note for a specific date."""
    if not blocks:
        return
        
    url = f"{CRAFT_API_BASE}/blocks"
    headers = {
        "Authorization": f"Bearer {CRAFT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "blocks": blocks,
        "position": {"position": "end", "date": target_date_str}
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Error sending to Craft: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return False

def main():
    # Calculate yesterday's date
    yesterday = date.today() - timedelta(days=1)
    yesterday_str = yesterday.isoformat()
    
    print(f"Starting granular sync for yesterday: {yesterday_str}...")
    
    docs = get_granola_documents()
    target_docs = filter_meetings_by_date(docs, yesterday)
    
    if not target_docs:
        print(f"No meetings found for {yesterday_str}.")
        return
        
    print(f"Found {len(target_docs)} meetings. Syncing one by one...")
    
    # 1. Start with a main header for yesterday
    send_blocks_to_craft([{
        "type": "text",
        "textStyle": "h1",
        "markdown": f"☕️ Granola Meetings ({yesterday_str})"
    }], yesterday_str)
    
    for doc in target_docs:
        title = doc.get("title") or "Untitled Meeting"
        print(f"Syncing: {title}...")
        
        # Fetch Summary
        panels = get_document_panels(doc['id'])
        summary_html = ""
        for panel in panels:
            if panel.get("title") == "Summary":
                summary_html = panel.get("original_content", "")
                break
        content_md = html_to_markdown(summary_html) if summary_html else "No summary available."
        
        # Fetch Transcript
        transcript_segments = get_document_transcript(doc['id'])
        transcript_text = format_transcript(transcript_segments)
        
        # Build blocks for THIS meeting
        meeting_blocks = [
            {
                "type": "text",
                "textStyle": "h2",
                "markdown": title
            },
            {
                "type": "text",
                "markdown": content_md
            },
            {
                "type": "page",
                "textStyle": "card",
                "markdown": "📄 Full Transcript",
                "content": [
                    {
                        "type": "text",
                        "markdown": transcript_text if len(transcript_text) < 50000 else transcript_text[:50000] + "\n\n... (transcript too long, truncated)"
                    }
                ]
            },
            {
                "type": "text",
                "markdown": "---"
            }
        ]
        
        success = send_blocks_to_craft(meeting_blocks, yesterday_str)
        if success:
            print(f"✅ Successfully synced: {title}")
        else:
            print(f"❌ Failed to sync: {title}")

if __name__ == "__main__":
    main()
