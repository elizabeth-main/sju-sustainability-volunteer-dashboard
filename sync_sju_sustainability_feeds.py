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
    },
    {
        "name": "Lower Merion Conservancy",
        "type": "ical",
        # The Events Calendar plugin iCal export for Mill Creek & Lower Merion workdays (~3.2 mi)
        "url": "https://lmconservancy.org/events/?ical=1",
        "default_lat": 40.0351,
        "default_lon": -75.2782
    },
    {
        "name": "Schuylkill Center for Environmental Education",
        "type": "ical",
        # Forest restoration, bird counts, and trail maintenance in Upper Roxborough (~5.5 mi)
        "url": "https://www.schuylkillcenter.org/events/?ical=1",
        "default_lat": 40.0619,
        "default_lon": -75.2478
    },
    {
        "name": "Friends of the Wissahickon (FOW)",
        "type": "ical",
        # Trail cleanups, erosion control, and invasive species sweeps in Wissahickon Valley Park (~6.1 mi)
        "url": "https://fow.org/events/?ical=1",
        "default_lat": 40.0392,
        "default_lon": -75.2045
    },
    {
        "name": "John Heinz National Wildlife Refuge at Tinicum",
        "type": "rss",
        # USFWS public updates and volunteer marsh cleanup events in Southwest Philly (~8.5 mi)
        "url": "https://www.fws.gov/refuge/john-heinz-tinicum/rss.xml",
        "default_lat": 39.8891,
        "default_lon": -75.2575
    },
    {
        "name": "Pennsylvania Horticultural Society (PHS)",
        "type": "rss",
        # Tree Tenders plantings, public garden prep, and urban agriculture across Philly (~5.2 mi)
        "url": "https://phsonline.org/feed",
        "default_lat": 39.9537,
        "default_lon": -75.1742
    },
    {
        "name": "Overbrook Environmental Education Center (OEEC)",
        "type": "rss",
        # Environmental justice, urban farming, and neighborhood cleanups adjacent to Hawk Hill (~1.1 mi)
        "url": "https://overbrookcenter.net/feed/",
        "default_lat": 39.9836,
        "default_lon": -75.2443
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
