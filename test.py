import os, json, requests
import datetime

key = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhwcXdid2V6ZGljZnR4cnl2Z3ZyIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjEzNjIyMjQsImV4cCI6MjA3NjkzODIyNH0.yau0uFhjBk1_aWI7dqYrxYDAWP8OycuncBz9RBlzeTI'
url = 'https://xpqwbwezdicftxryvgvr.supabase.co'

test = {
    'id': '200',
    'timestamp': '2025-10-25T06:04:26.633Z',
    'txn_id': '200',
    'current_page': 'test',
    'activity': 'test',
    'user_id': 'test',
    'ip_address': '192.168.127.12',
    'user_agent': 'test',
    'details': {'test':'test'},
    'source': 'test'
}

headers = {
    "apikey": key,
    "Authorization": f"Bearer {key}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates"
}

endpoint = f"{url}/rest/v1/activity_logs"

try:
    response = requests.post(endpoint, json=test, headers=headers)
    response.raise_for_status()
except Exception as e:
    print(e)
