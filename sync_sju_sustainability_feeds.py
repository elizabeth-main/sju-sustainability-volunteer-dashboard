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
# 1. CAMPUS LOCATION & CONFIGURATION
# -------------------------------------------------------------------
HAWK_HILL_LAT = 39.9950
HAWK_HILL_LON = -75.2386
MAX_RADIUS_MILES = 10.0

# Live RSS & iCal Feed Directory of Local Philly Sustainability Organizations
FEEDS_TO_SCRAPE = [
    {
        "name": "Fairmount Park Conservancy",
        "type": "rss",
        "url": "https://fairmountpark.org/feed/",  # Public WordPress event RSS
        "default_lat": 39.9825,
        "default_lon": -75.2111
    },
    {
        "name": "Bartram's Garden",
        "type": "ical",
        "url": "https://bartramsgarden.org/events/?ical=1",  # iCal Feed URL
        "default_lat": 39.9328,
        "default_lon": -75.2120
    },
    {
        "name": "SJU Sustainability Calendar",
        "type": "ical",
        "url": "https://sju.edu/events/ical",  # Example SJU Campus iCal Link
        "default_lat": HAWK_HILL_LAT,
        "default_lon": HAWK_HILL_LON
    }
]

# -------------------------------------------------------------------
# 2. HAVERSINE DISTANCE HELPER
# -------------------------------------------------------------------
def calculate_distance_miles(lat1, lon1, lat2, lon2):
    """Calculates distance between two lat/lon coordinates in miles."""
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
        for entry in parsed_feed.entries[:10]:  # Inspect 10 latest entries
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
            for component in cal.walk('vevent'):
                summary = str(component.get('summary', ''))
                description = str(component.get('description', ''))
                location = str(component.get('location', ''))
                start_time = component.get('dtstart')
                
                raw_entries.append({
                    "source_org": feed_info["name"],
                    "raw_title": summary,
                    "raw_text": f"Date/Time: {start_time.dt if start_time else 'TBD'}. Location: {location}. Details: {description}",
                    "link": feed_info["url"],
                    "lat": feed_info["default_lat"],
                    "lon": feed_info["default_lon"]
                })
    except Exception as e:
        print(f"⚠️ Warning: Failed to fetch iCal feed for {feed_info['name']}: {e}")
    return raw_entries

# -------------------------------------------------------------------
# 4. GEMINI AI STRUCTURE & FILTERING PIPELINE
# -------------------------------------------------------------------
def process_and_structure_events(raw_events):
    client = genai.Client()
    processed_opportunities = []

    print(f"\n🔄 Processing {len(raw_events)} raw feed items with Gemini AI...\n")

    for idx, item in enumerate(raw_events, 1):
        dist_miles = calculate_distance_miles(HAWK_HILL_LAT, HAWK_HILL_LON, item["lat"], item["lon"])
        
        # Enforce strict 10-mile radius check
        if dist_miles > MAX_RADIUS_MILES:
            print(f"❌ Skipped #{idx}: Exceeds 10-mile radius ({round(dist_miles, 1)} miles away)")
            continue

        prompt = f"""
        You are an AI data engineer for Saint Joseph's University Sustainability Dashboard.
        Examine the following raw feed item from {item['source_org']}:

        Title: "{item['raw_title']}"
        Text Content: "{item['raw_text']}"

        Task:
        1. Determine if this event is related to environmental sustainability or volunteering (e.g., cleanups, tree planting, gardening, food waste, recycling, eco-education).
        2. If NOT related to sustainability or volunteering, return JSON with "is_sustainability": false.
        3. If IT IS related, return JSON with:
           - "is_sustainability": true
           - "title": Clean, concise event title
           - "organization": Partner name
           - "type": "on-campus" if at SJU/Hawk Hill, otherwise "off-campus"
           - "category": One of ["Cleanups", "Forestry & Gardening", "Food Waste", "Education & Advocacy"]
           - "date": Human-readable date & time string
           - "location": Specific venue or meeting point
           - "description": 2-sentence summary tailored for college volunteers
           - "spotsLeft": Estimated available spots integer (e.g. 10)
           - "tags": Array of 3 short relevant topic tags
        """

        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                )
            )
            
            structured = json.loads(response.text)
            
            if structured.get("is_sustainability"):
                structured["id"] = idx
                structured["distanceMiles"] = round(dist_miles, 1)
                structured["registrationUrl"] = item["link"]
                processed_opportunities.append(structured)
                print(f"✅ Added: \"{structured['title']}\" ({round(dist_miles, 1)} mi from Hawk Hill)")
            else:
                print(f"⏩ Filtered out: \"{item['raw_title']}\" (Not sustainability/volunteer related)")

        except Exception as err:
            print(f"⚠️ Error parsing event #{idx} with Gemini: {err}")

    return processed_opportunities

# -------------------------------------------------------------------
# 5. MAIN EXECUTION
# -------------------------------------------------------------------
def main():
    all_raw_events = []

    print("📡 Ingesting live feeds from local Philadelphia partners...")
    for feed in FEEDS_TO_SCRAPE:
        print(f"  • Fetching {feed['type'].upper()} feed from {feed['name']}...")
        if feed["type"] == "rss":
            all_raw_events.extend(fetch_rss_events(feed))
        elif feed["type"] == "ical":
            all_raw_events.extend(fetch_ical_events(feed))

    valid_events = process_and_structure_events(all_raw_events)

    # Save cleanly structured output file for dashboard frontend
    output_filename = "sju_dashboard_opportunities.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(valid_events, f, indent=2)

    print(f"\n🎉 Successfully saved {len(valid_events)} active sustainability opportunities to '{output_filename}'!")

if __name__ == "__main__":
    main()
