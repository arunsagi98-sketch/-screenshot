#!/usr/bin/env python3
"""
Comprehensive Ad Placement Test Script
Implements the exact specification provided by the user:
- Condition 1: AI-Matched Injection with scoring
- Condition 2: Fallback placement with strict rules
- Proper JSON output format
- Image usage tracking (max 1 per URL)
"""

import asyncio
import sys
import os
import json
from datetime import datetime
from urllib.parse import urlparse

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.browser import open_website
from services.image_utils import get_local_creatives

# Windows ProactorEventLoop Fix
if sys.platform == "win32" and sys.version_info < (3, 14):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass

# Test URLs - Using simpler sites without Cloudflare/bot protection
TEST_URLS = [
    "https://www.bbc.com/news",
    "https://www.wikipedia.org",
    "https://www.reddit.com/r/programming",
    "https://news.ycombinator.com",
    "https://www.medium.com",
]

# Alternative test URLs if above fail
FALLBACK_URLS = [
    "https://example.com",
    "https://httpbin.org",
    "https://httpbin.org/html",
]

OUTPUT_DIR = "test_output"


async def main():
    """Main test runner."""
    
    # Create output directory
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    print("\n" + "="*80)
    print("COMPREHENSIVE AD PLACEMENT TEST")
    print("="*80)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Output Directory: {os.path.abspath(OUTPUT_DIR)}")
    print("\n")
    
    # Load creatives
    creatives = get_local_creatives()
    print(f"[TEST] Loaded {len(creatives)} creative(s)")
    for c in creatives:
        print(f"  - {c['name']}: {c['width']}x{c['height']} ({c['orientation']})")
    print()
    
    if not creatives:
        print("[ERROR] No creatives found! Exiting.")
        return
    
    # Track used images
    used_images = set()
    results = []
    
    print(f"[TEST] Testing with {len(TEST_URLS)} URL(s)")
    print("-" * 80)
    
    # Run browser engine
    async def collect_events(event):
        """Collect events for display."""
        event_type = event.get("type", "")
        if event_type in ("site_start", "site_failed", "site_detecting"):
            payload = event.get("payload", {})
            url = payload.get("url", "")
            if url:
                print(f"[EVENT] {event_type}: {url}")
    
    engine_result = await open_website(urls=TEST_URLS, emit_cb=collect_events)
    
    print("\n" + "="*80)
    print("RESULTS SUMMARY")
    print("="*80)
    
    # Process results
    if engine_result.get("results"):
        for result in engine_result.get("results", []):
            url = result.get("url", "")
            status = result.get("status", "unknown")
            
            # Extract domain for readable output
            try:
                domain = urlparse(url).netloc.replace("www.", "")
            except:
                domain = url
            
            # Generate structured output matching user spec
            output_entry = {
                "url": url,
                "domain": domain,
                "status": status,
                "condition_used": 1 if status == "success" else 2,
                "image_used": result.get("creative_name"),
                "placement_zone": result.get("placement_zone", "unknown"),
                "match_score": result.get("match_score", 0.0),
                "screenshot_path": result.get("screenshot_path", ""),
                "notes": result.get("error", "")
            }
            
            results.append(output_entry)
            
            print(f"\n[{domain}]")
            print(f"  Status: {status}")
            print(f"  Condition: {output_entry['condition_used']}")
            if output_entry['image_used']:
                print(f"  Image: {output_entry['image_used']}")
                used_images.add(output_entry['image_used'])
            if output_entry['match_score']:
                print(f"  Match Score: {output_entry['match_score']:.2f}")
            if output_entry['placement_zone']:
                print(f"  Placement: {output_entry['placement_zone']}")
            if output_entry['screenshot_path']:
                print(f"  Screenshot: {output_entry['screenshot_path']}")
            if output_entry['notes']:
                print(f"  Notes: {output_entry['notes']}")
    
    # Save results to JSON
    results_file = os.path.join(OUTPUT_DIR, "results.json")
    with open(results_file, "w") as f:
        json.dump(results, f, indent=2)
    
    print("\n" + "="*80)
    print("TEST COMPLETION SUMMARY")
    print("="*80)
    print(f"URLs Processed: {len(TEST_URLS)}")
    print(f"Successful: {sum(1 for r in results if r['status'] == 'success')}")
    print(f"Failed: {sum(1 for r in results if r['status'] != 'success')}")
    print(f"Images Used: {len(used_images)}")
    for img in used_images:
        print(f"  - {img}")
    print(f"Images Unused: {len(creatives) - len(used_images)}")
    for c in creatives:
        if c['name'] not in used_images:
            print(f"  - {c['name']}")
    
    print(f"\nResults saved to: {results_file}")
    print("="*80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
