"""Test network monitoring with a real agent on https://dev.petal.net/"""

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv

from browser_use import Agent
from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.profile import ViewportSize
from browser_use.llm.openai.chat import ChatOpenAI

# Load environment variables
load_dotenv()


async def test_network_monitoring_with_real_agent():
    """Test network monitoring with a real agent browsing dev.petal.net"""
    print("🚀 Starting real network monitoring test...")

    # Configure browser with network monitoring enabled
    browser_profile = BrowserProfile(
        headless=False,  # Keep visible to see what's happening
        window_size=ViewportSize(width=1280, height=720),
        keep_alive=True
    )

    # Create browser session
    browser_session = BrowserSession(browser_profile=browser_profile)

    # Set up LLM
    llm = ChatOpenAI(model="gpt-4o-mini")

    # Create agent
    agent = Agent(
        task="Navigate to https://dev.petal.net/ and explore the website to find information about their services. Pay attention to any network requests that are made.",
        llm=llm,
        browser_session=browser_session,
        use_vision=True
    )

    try:
        print("📱 Navigating to https://dev.petal.net/...")

        # First navigate directly to the correct URL
        await browser_session.navigate_to("https://dev.petal.net/")
        await asyncio.sleep(3)  # Wait for initial page load

        # Start the agent
        result = await agent.run()

        print(f"✅ Agent completed task: {result}")

        # Wait a moment for any final requests to complete
        await asyncio.sleep(2)

        # Now analyze the network activity
        print("\n🔍 Analyzing network activity...")

        # Get network summary
        network_summary = browser_session.get_network_summary()
        print(f"📊 Network Summary: {json.dumps(network_summary, indent=2)}")

        # Get recent API requests
        api_requests = browser_session.get_network_requests(limit=10, request_type='api')
        print(f"\n🔄 Recent API requests ({len(api_requests)}):")
        for i, req in enumerate(api_requests[-5:], 1):  # Show last 5
            status = f"✅ {req['response_status']}" if req.get('response_status', 0) < 400 else f"❌ {req.get('response_status', 'Failed')}"
            duration = f"{req['duration']:.2f}s" if req.get('duration') else "N/A"
            ui_section = req.get('ui_section', 'Unknown')
            print(f"  {i}. {status} {req['method']} {req['url'][:80]}...")
            print(f"     Duration: {duration}, UI Section: {ui_section}")
            if req.get('likely_ui_trigger'):
                print(f"     Trigger: {req['likely_ui_trigger']}")

        # Get user-triggered requests
        user_requests = browser_session.get_user_triggered_requests(limit=5)
        print(f"\n👤 User-triggered requests ({len(user_requests)}):")
        for i, req in enumerate(user_requests, 1):
            status = f"✅ {req['response_status']}" if req.get('response_status', 0) < 400 else f"❌ {req.get('response_status', 'Failed')}"
            print(f"  {i}. {status} {req['method']} {req['url'][:60]}...")
            print(f"     Trigger: {req.get('likely_ui_trigger', 'Unknown')}")
            print(f"     UI Section: {req.get('ui_section', 'Unknown')}")

        # Analyze recent user activity
        recent_activity = browser_session.analyze_recent_user_activity(seconds_back=60)
        print(f"\n📈 Recent Activity Analysis (last 60s):")
        print(f"  Total requests: {recent_activity['total_requests']}")
        print(f"  User-triggered: {recent_activity['user_triggered_requests']}")
        print(f"  API calls: {recent_activity['api_calls']}")
        print(f"  Failed requests: {recent_activity['failed_requests']}")

        # Show recent user actions
        if recent_activity.get('recent_user_actions'):
            print(f"\n🎯 Recent User Actions:")
            for i, action in enumerate(recent_activity['recent_user_actions'], 1):
                status = f"✅ {action['status']}" if action.get('status', 0) < 400 else f"❌ {action.get('status', 'Failed')}"
                duration = f"{action['duration']:.2f}s" if action.get('duration') else "N/A"
                print(f"  {i}. {status} {action['url'][:60]}... ({duration})")
                print(f"     Trigger: {action.get('trigger', 'Unknown')}")

        # Get UI activity summary
        ui_summary = browser_session.get_ui_activity_summary()
        print(f"\n🎨 UI Activity Summary:")
        print(f"  Active sections: {ui_summary['total_sections']}")
        if ui_summary.get('most_active_section'):
            most_active = ui_summary['most_active_section']
            print(f"  Most active: {most_active[0]} ({most_active[1]} requests)")

        print(f"\n📋 Section breakdown:")
        for section, count in ui_summary.get('section_breakdown', {}).items():
            print(f"    {section}: {count} requests")

        # Test specific section filtering
        print(f"\n🔍 Testing UI section filtering...")
        header_requests = browser_session.get_requests_by_ui_section('header', limit=3)
        print(f"  Header requests: {len(header_requests)}")

        main_requests = browser_session.get_requests_by_ui_section('main', limit=3)
        print(f"  Main content requests: {len(main_requests)}")

        # Ask the agent to analyze the network data
        print(f"\n🤖 Asking agent to analyze network activity...")

        # Create a new task for network analysis using the new network monitoring tools
        analysis_agent = Agent(
            task=f"""I have network monitoring tools available. Analyze the network requests made while browsing https://dev.petal.net/

            Use these network monitoring tools:
            - get_network_summary: Get overall statistics
            - get_network_requests: Get recent network requests (use request_type='api' for API calls)
            - get_user_triggered_requests: Get requests triggered by user interactions
            - analyze_recent_user_activity: Analyze recent activity patterns
            - get_ui_activity_summary: Get UI section activity breakdown

            Tell me:
            1. What types of network requests were made?
            2. Which UI sections were most active?
            3. What user interactions triggered API calls?
            4. Were there any interesting patterns in the network activity?

            Use the actual network monitoring tools to get this data - don't guess.""",
            llm=llm,
            browser_session=browser_session,
            use_vision=False  # Don't need vision for data analysis
        )

        analysis_result = await analysis_agent.run()
        print(f"🧠 Agent's Network Analysis:\n{analysis_result}")

    except Exception as e:
        print(f"❌ Error during test: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Clean up
        try:
            await browser_session.stop()
            print("🧹 Browser session stopped")
        except Exception as e:
            print(f"⚠️ Error stopping browser: {e}")


async def main():
    """Main function to run the test"""
    await test_network_monitoring_with_real_agent()


if __name__ == "__main__":
    print("🌐 Testing Network Monitoring with Real Agent")
    print("=" * 50)
    asyncio.run(main())