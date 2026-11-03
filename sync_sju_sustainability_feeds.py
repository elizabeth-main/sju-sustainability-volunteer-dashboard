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
# 4. LOAD MANUAL OPPORTUNITIES
# -------------------------------------------------------------------
def load_manual_events(filename="manual_opportunities.json"):
    """Loads manually maintained events if the file exists."""
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    print(f"📋 Loaded {len(data)} manual opportunities from {filename}")
                    return data
        except Exception as e:
            print(f"⚠️ Error reading manual events from {filename}: {e}")
    else:
        print(f"ℹ️ {filename} not found. Proceeding with feed items only.")
    return []

# -------------------------------------------------------------------
# 5. GEMINI AI PARSER & RELEVANCE FILTER
# -------------------------------------------------------------------
def process_and_structure_events(raw_events, starting_id=100):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("⚠️ Warning: GEMINI_API_KEY environment variable is not set. Skipping AI parsing.")
        return []

    client = genai.Client()
    processed_opportunities = []

    print(f"\n🔄 Evaluating {len(raw_events)} raw feed items with Gemini AI...\n")

    for idx, item in enumerate(raw_events, start=starting_id):
        dist_miles = calculate_distance_miles(HAWK_HILL_LAT, HAWK_HILL_LON, item["lat"], item["lon"])
        
        # Enforce strict 10-mile radius gate
        if dist_miles > MAX_RADIUS_MILES:
            print(f"❌ Skipped #{idx}: Exceeds 10-mile radius ({round(dist_miles, 1)} miles away)")
            continue

        prompt = f"""
        You are an AI data engineer for Saint Joseph's University Sustainability Dashboard (Hawk Hill Campus).
        Examine the following raw feed item from {item['source_org']}:

        Title: "{item['raw_title']}"
        Text Content: "{item['raw_text']}"

        Task:
        1. Determine if this event is related to environmental sustainability or volunteering (e.g., trash cleanups, tree planting, gardening, food waste recovery, recycling, watershed monitoring, nature conservation).
        2. If NOT related to sustainability or volunteering, return a JSON object with: {{"is_sustainability": false}}
        3. If IT IS related, return a JSON object with:
           - "is_sustainability": true
           - "title": Clean, concise event title
           - "organization": Partner name
           - "type": "on-campus" if held at SJU/Hawk Hill, otherwise "off-campus"
           - "category": One of ["Cleanups", "Forestry & Gardening", "Food Waste", "Education & Advocacy"]
           - "date": Formatted human-readable date & time string
           - "location": Specific venue or meeting point
           - "description": 2-sentence summary tailored for student volunteers
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
                structured["link"] = item["link"]
                structured["badgeColor"] = "bg-emerald-100 text-emerald-800" if structured.get("type") == "on-campus" else "bg-blue-100 text-blue-800"
                
                processed_opportunities.append(structured)
                print(f"✅ Added: \"{structured['title']}\" ({round(dist_miles, 1)} mi from Hawk Hill)")
            else:
                print(f"⏩ Filtered out: \"{item['raw_title']}\" (Not sustainability/volunteer related)")

        except Exception as err:
            print(f"⚠️ Error parsing event #{idx} with Gemini: {err}")

    return processed_opportunities

# -------------------------------------------------------------------
# 6. MAIN PIPELINE
# -------------------------------------------------------------------
def main():
    # 1. Load manual campus opportunities
    manual_events = load_manual_events("manual_opportunities.json")

    # 2. Ingest raw RSS & iCal feeds
    all_raw_events = []
    print("📡 Ingesting live feeds from local Philadelphia partners...")
    for feed in FEEDS_TO_SCRAPE:
        print(f"  • Fetching {feed['type'].upper()} feed from {feed['name']}...")
        if feed["type"] == "rss":
            all_raw_events.extend(fetch_rss_events(feed))
        elif feed["type"] == "ical":
            all_raw_events.extend(fetch_ical_events(feed))

    # 3. Filter and parse feed events with Gemini
    scraped_events = process_and_structure_events(all_raw_events, starting_id=len(manual_events) + 1)

    # 4. Merge: manual opportunities appear first, followed by live scraped events
    combined_events = manual_events + scraped_events

    # 5. Output unified JSON file for the dashboard frontend
    output_filename = "sju_dashboard_opportunities.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(combined_events, f, indent=2)

    print(f"\n🎉 Successfully published {len(combined_events)} total opportunities ({len(manual_events)} manual, {len(scraped_events)} automated) to '{output_filename}'!")

if __name__ == "__main__":
    main()
