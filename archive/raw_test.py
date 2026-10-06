import requests
import urllib3

# Suppress the "unsafe connection" SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

IP = "192.168.1.226"

try:
    print(f"Knocking on {IP}'s door...")
    # Attempting to hit the Gateway's public status page
    res = requests.get(f"https://{IP}/api/status", verify=False, timeout=5)
    
    print(f"SUCCESS! Gateway responded with Status Code: {res.status_code}")
    print(f"Raw Data: {res.text}")
    
except Exception as e:
    print(f"NETWORK BLOCKED: {e}")
