import os
import re
import json
import math
import requests
import feedparser
from datetime import datetime
from icalendar import Calendar
from google import genai
from google.genai import types

# -------------------------------------------------------------------
# 1. CAMPUS LOCATION & RADIUS LIMIT
# Address: 5600 City Ave, Philadelphia, PA 19131
# -------------------------------------------------------------------
HAWK_HILL_LAT = 39.9950
HAWK_HILL_LON = -75.2386
MAX_RADIUS_MILES = 10.0

# Directory of Local Philadelphia Sustainability RSS & iCal Feeds
FEEDS_TO_SCRAPE = [
    {
        "name": "Fairmount Park Conservancy",
        "type": "rss",
        "url": "https://fairmountpark.org/feed/",
        "default_lat": 39.9825,
        "default_lon": -75.2111
    },
    {
        "name": "Bartram's Garden",
        "type": "ical",
        "url": "https://bartramsgarden.org/events/?ical=1",
        "default_lat": 39.9328,
        "default_lon": -75.2120
    },
    {
        "name": "SJU Campus Events",
        "type": "ical",
        "url": "https://sju.edu/events/ical",
        "default_lat": HAWK_HILL_LAT,
        "default_lon": HAWK_HILL_LON
    }
]

# -------------------------------------------------------------------
# 2. HAVERSINE DISTANCE HELPER
# -------------------------------------------------------------------
def calculate_distance_miles(lat1, lon1, lat2, lon2):
    """Calculates the great-circle distance between two points in miles."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# -------------------------------------------------------------------
# 3. FEED FETCHERS (RSS & iCal)
# -------------------------------------------------------------------
def fetch_rss_events(feed_info):
    raw_entries = []
    try:
        parsed_feed = feedparser.parse(feed_info["url"])
        for entry in parsed_feed.entries[:10]:
            raw_entries.append({
                "source_org": feed_info["name"],
                "raw_title": entry.get("title", ""),
                "raw_text": entry.get("summary", "") or entry.get("description", ""),
                "link": entry.get("link", ""),
                "lat": feed_info["default_lat"],
                "lon": feed_info["default_lon"]
            })
    except Exception as e:
        print(f"⚠️ Warning: Failed to fetch RSS feed for {feed_info['name']}: {e}")
    return raw_entries

def fetch_ical_events(feed_info):
    raw_entries = []
    try:
        response = requests.get(feed_info["url"], timeout=10)
        if response.status_code == 200:
            cal = Calendar.from_ical(response.content)
            for component in cal.walk('vevent
