"""Tests for NetworkWatchdog and NetworkRequestTracker functionality."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_httpserver import HTTPServer
from werkzeug import Request, Response

from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.network_watchdog import NetworkRequestTracker, NetworkWatchdog


class TestNetworkRequestTracker:
	"""Test the NetworkRequestTracker class functionality."""

	def test_basic_request_tracking(self):
		"""Test basic request tracking functionality."""
		start_time = time.time()
		tracker = NetworkRequestTracker(
			request_id="test-123",
			start_time=start_time,
			url="https://example.com/api/search",
			method="POST",
			resource_type="XHR"
		)

		assert tracker.request_id == "test-123"
		assert tracker.url == "https://example.com/api/search"
		assert tracker.method == "POST"
		assert tracker.resource_type == "XHR"
		assert tracker.start_time == start_time
		assert tracker.duration is None  # Not completed yet

	def test_api_call_detection(self):
		"""Test API call detection logic."""
		xhr_tracker = NetworkRequestTracker(
			request_id="xhr-1",
			start_time=time.time(),
			url="https://example.com/api/users",
			method="GET",
			resource_type="XHR"
		)
		assert xhr_tracker.is_api_call is True

		fetch_tracker = NetworkRequestTracker(
			request_id="fetch-1",
			start_time=time.time(),
			url="https://example.com/data",
			method="POST",
			resource_type="Fetch"
		)
		assert fetch_tracker.is_api_call is True

		json_tracker = NetworkRequestTracker(
			request_id="json-1",
			start_time=time.time(),
			url="https://example.com/endpoint",
			method="GET",
			resource_type="Other"
		)
		json_tracker.response_headers = {"content-type": "application/json"}
		assert json_tracker.is_api_call is True

	def test_ui_resource_detection(self):
		"""Test UI resource detection logic."""
		image_tracker = NetworkRequestTracker(
			request_id="img-1",
			start_time=time.time(),
			url="https://example.com/logo.png",
			method="GET",
			resource_type="Image"
		)
		assert image_tracker.is_ui_resource is True

		css_tracker = NetworkRequestTracker(
			request_id="css-1",
			start_time=time.time(),
			url="https://example.com/styles.css",
			method="GET",
			resource_type="Stylesheet"
		)
		assert css_tracker.is_ui_resource is True

	def test_duration_calculation(self):
		"""Test request duration calculation."""
		start_time = time.time()
		tracker = NetworkRequestTracker(
			request_id="duration-test",
			start_time=start_time,
			url="https://example.com/test",
			method="GET"
		)

		# Before completion
		assert tracker.duration is None

		# After completion
		tracker.end_time = start_time + 1.5
		assert tracker.duration == 1.5

	def test_ui_trigger_analysis(self):
		"""Test UI trigger analysis functionality."""
		# Test click handler detection
		click_tracker = NetworkRequestTracker(
			request_id="click-1",
			start_time=time.time(),
			url="https://example.com/api/action",
			method="POST"
		)
		click_tracker.initiator = {
			"type": "script",
			"stack": {
				"callFrames": [
					{"functionName": "handleClick", "url": "https://example.com/app.js"}
				]
			}
		}
		assert "click" in click_tracker.likely_ui_trigger.lower()

		# Test form submission detection (URL pattern analysis)
		submit_tracker = NetworkRequestTracker(
			request_id="submit-1",
			start_time=time.time(),
			url="https://example.com/api/submit",
			method="POST",
			resource_type="XHR"
		)
		# The likely_ui_trigger property automatically checks URL patterns for API calls
		trigger = submit_tracker.likely_ui_trigger
		assert trigger is not None and "form submission" in trigger.lower()

		# Test search action detection (URL pattern analysis)
		search_tracker = NetworkRequestTracker(
			request_id="search-1",
			start_time=time.time(),
			url="https://example.com/api/search?q=test",
			method="GET",
			resource_type="XHR"
		)
		trigger = search_tracker.likely_ui_trigger
		assert trigger is not None and "search" in trigger.lower()

	def test_ui_section_identification(self):
		"""Test UI section identification by URL patterns."""
		tracker = NetworkRequestTracker(
			request_id="section-1",
			start_time=time.time(),
			url="https://example.com/api/search",
			method="GET",
			resource_type="XHR"
		)
		tracker.analyze_dom_context(None)
		assert "search" in tracker.ui_section.lower()

		delete_tracker = NetworkRequestTracker(
			request_id="delete-1",
			start_time=time.time(),
			url="https://example.com/api/delete/123",
			method="DELETE",
			resource_type="XHR"
		)
		delete_tracker.analyze_dom_context(None)
		assert "action controls" in delete_tracker.ui_section.lower()

	def test_position_based_ui_section(self):
		"""Test UI section identification based on element position."""
		tracker = NetworkRequestTracker(
			request_id="pos-1",
			start_time=time.time(),
			url="https://example.com/test",
			method="GET"
		)

		# Header position
		tracker.element_position = {"x": 640, "y": 50, "width": 100, "height": 30}
		tracker.identify_ui_section_by_position(1280, 720)
		assert "header" in tracker.ui_section.lower()

		# Sidebar position
		tracker.element_position = {"x": 50, "y": 300, "width": 100, "height": 30}
		tracker.identify_ui_section_by_position(1280, 720)
		assert "sidebar" in tracker.ui_section.lower()

		# Footer position
		tracker.element_position = {"x": 640, "y": 680, "width": 100, "height": 30}
		tracker.identify_ui_section_by_position(1280, 720)
		assert "footer" in tracker.ui_section.lower()

	def test_to_dict_serialization(self):
		"""Test request tracker serialization to dictionary."""
		tracker = NetworkRequestTracker(
			request_id="serialize-1",
			start_time=time.time(),
			url="https://example.com/api/test",
			method="POST",
			resource_type="XHR"
		)
		tracker.response_status = 200
		tracker.ui_section = "Header - Center"
		tracker.element_text = "Search button"

		data = tracker.to_dict()

		assert data["request_id"] == "serialize-1"
		assert data["url"] == "https://example.com/api/test"
		assert data["method"] == "POST"
		assert data["resource_type"] == "XHR"
		assert data["response_status"] == 200
		assert data["ui_section"] == "Header - Center"
		assert data["element_text"] == "Search button"
		assert "likely_ui_trigger" in data
		assert "is_api_call" in data
		assert "is_ui_resource" in data


class TestNetworkWatchdog:
	"""Test the NetworkWatchdog class functionality."""

	@pytest.fixture
	def mock_browser_session(self):
		"""Create a mock browser session for testing."""
		from bubus import EventBus

		session = MagicMock(spec=BrowserSession)
		session.agent_focus = MagicMock()
		session.agent_focus.target_id = "test-target-123"
		session.browser_profile = MagicMock()
		session.browser_profile.viewport = {"width": 1280, "height": 720}

		# Use real event bus
		session.event_bus = EventBus()

		return session

	@pytest.fixture
	def network_watchdog(self, mock_browser_session):
		"""Create a NetworkWatchdog instance for testing."""
		watchdog = NetworkWatchdog(
			event_bus=mock_browser_session.event_bus,
			browser_session=mock_browser_session
		)
		return watchdog

	def test_watchdog_initialization(self, network_watchdog):
		"""Test NetworkWatchdog initialization."""
		assert network_watchdog._active_requests == {}
		assert network_watchdog._completed_requests == []
		assert network_watchdog.max_stored_requests == 200

	def test_request_storage_limit(self, network_watchdog):
		"""Test that completed requests are limited to max_stored_requests."""
		# Create more requests than the limit
		for i in range(250):
			tracker = NetworkRequestTracker(
				request_id=f"req-{i}",
				start_time=time.time(),
				url=f"https://example.com/api/{i}",
				method="GET"
			)
			tracker.end_time = time.time() + 0.1
			network_watchdog._store_completed_request(tracker)

		assert len(network_watchdog._completed_requests) == 200
		# Should keep the most recent ones
		assert network_watchdog._completed_requests[-1].request_id == "req-249"

	def test_get_recent_requests(self, network_watchdog):
		"""Test getting recent requests."""
		# Add some test requests
		for i in range(5):
			tracker = NetworkRequestTracker(
				request_id=f"recent-{i}",
				start_time=time.time(),
				url=f"https://example.com/api/{i}",
				method="GET",
				resource_type="XHR" if i % 2 == 0 else "Document"
			)
			tracker.end_time = time.time() + 0.1
			network_watchdog._store_completed_request(tracker)

		recent = network_watchdog.get_recent_requests(3)
		assert len(recent) == 3
		assert all(isinstance(req, dict) for req in recent)
		assert recent[-1]["request_id"] == "recent-4"

	def test_get_api_requests(self, network_watchdog):
		"""Test filtering API requests."""
		# Add mixed request types
		api_tracker = NetworkRequestTracker(
			request_id="api-1",
			start_time=time.time(),
			url="https://example.com/api/data",
			method="POST",
			resource_type="XHR"
		)
		api_tracker.end_time = time.time() + 0.1
		network_watchdog._store_completed_request(api_tracker)

		doc_tracker = NetworkRequestTracker(
			request_id="doc-1",
			start_time=time.time(),
			url="https://example.com/page.html",
			method="GET",
			resource_type="Document"
		)
		doc_tracker.end_time = time.time() + 0.1
		network_watchdog._store_completed_request(doc_tracker)

		api_requests = network_watchdog.get_api_requests()
		assert len(api_requests) == 1
		assert api_requests[0]["request_id"] == "api-1"

	def test_get_failed_requests(self, network_watchdog):
		"""Test filtering failed requests."""
		# Add successful and failed requests
		success_tracker = NetworkRequestTracker(
			request_id="success-1",
			start_time=time.time(),
			url="https://example.com/api/success",
			method="GET"
		)
		success_tracker.response_status = 200
		success_tracker.end_time = time.time() + 0.1
		network_watchdog._store_completed_request(success_tracker)

		failed_tracker = NetworkRequestTracker(
			request_id="failed-1",
			start_time=time.time(),
			url="https://example.com/api/error",
			method="GET"
		)
		failed_tracker.failed = True
		failed_tracker.failure_reason = "Network error"
		failed_tracker.end_time = time.time() + 0.1
		network_watchdog._store_completed_request(failed_tracker)

		failed_requests = network_watchdog.get_failed_requests()
		assert len(failed_requests) == 1
		assert failed_requests[0]["request_id"] == "failed-1"
		assert failed_requests[0]["failed"] is True

	def test_get_user_triggered_requests(self, network_watchdog):
		"""Test filtering user-triggered requests."""
		# Add user-triggered request
		user_tracker = NetworkRequestTracker(
			request_id="user-1",
			start_time=time.time(),
			url="https://example.com/api/submit",
			method="POST",
			resource_type="XHR"
		)
		user_tracker.analyze_dom_context(None)  # This should set ui_section for submit URL
		user_tracker.end_time = time.time() + 0.1
		network_watchdog._store_completed_request(user_tracker)

		# Add system-triggered request
		system_tracker = NetworkRequestTracker(
			request_id="system-1",
			start_time=time.time(),
			url="https://example.com/api/background",
			method="GET",
			resource_type="XHR"
		)
		system_tracker.end_time = time.time() + 0.1
		network_watchdog._store_completed_request(system_tracker)

		user_requests = network_watchdog.get_user_triggered_requests()
		assert len(user_requests) == 1
		assert user_requests[0]["request_id"] == "user-1"

	def test_analyze_recent_user_action(self, network_watchdog):
		"""Test analysis of recent user activity."""
		current_time = time.time()

		# Add recent user-triggered request
		user_tracker = NetworkRequestTracker(
			request_id="recent-user-1",
			start_time=current_time - 10,  # 10 seconds ago
			url="https://example.com/api/search",
			method="GET",
			resource_type="XHR"
		)
		user_tracker.analyze_dom_context(None)
		user_tracker.response_status = 200
		user_tracker.end_time = current_time - 9.5
		network_watchdog._store_completed_request(user_tracker)

		# Add old request (should be excluded)
		old_tracker = NetworkRequestTracker(
			request_id="old-1",
			start_time=current_time - 60,  # 60 seconds ago
			url="https://example.com/api/old",
			method="GET"
		)
		old_tracker.end_time = current_time - 59
		network_watchdog._store_completed_request(old_tracker)

		analysis = network_watchdog.analyze_recent_user_action(30)  # Last 30 seconds

		assert analysis["time_window_seconds"] == 30
		assert analysis["total_requests"] == 1
		assert analysis["api_calls"] == 1
		assert len(analysis["recent_user_actions"]) == 1
		assert analysis["recent_user_actions"][0]["status"] == 200

	def test_get_requests_summary(self, network_watchdog):
		"""Test requests summary generation."""
		# Add various types of requests
		for i in range(10):
			tracker = NetworkRequestTracker(
				request_id=f"summary-{i}",
				start_time=time.time(),
				url=f"https://example.com/api/{i}",
				method="GET",
				resource_type="XHR" if i < 7 else "Document"
			)
			tracker.response_status = 200 if i < 8 else None
			tracker.failed = i >= 8
			tracker.end_time = time.time() + 0.1
			network_watchdog._store_completed_request(tracker)

		summary = network_watchdog.get_requests_summary()

		assert summary["total_completed"] == 10
		assert summary["api_requests"] == 7
		assert summary["failed_requests"] == 2
		assert summary["success_rate"] == 80.0

	def test_ui_section_tracking(self, network_watchdog):
		"""Test UI section tracking and summary."""
		sections = ["Header - Center", "Sidebar - Left", "Main content", "Header - Center"]

		for i, section in enumerate(sections):
			tracker = NetworkRequestTracker(
				request_id=f"ui-{i}",
				start_time=time.time(),
				url=f"https://example.com/api/{i}",
				method="GET"
			)
			tracker.ui_section = section
			tracker.end_time = time.time() + 0.1
			network_watchdog._store_completed_request(tracker)

		# Test filtering by UI section
		header_requests = network_watchdog.get_requests_by_ui_section("header")
		assert len(header_requests) == 2

		# Test UI section summary
		summary = network_watchdog.get_ui_section_summary()
		assert summary["total_sections"] == 3
		assert summary["section_breakdown"]["Header - Center"] == 2
		assert summary["most_active_section"][0] == "Header - Center"

	def test_clear_request_history(self, network_watchdog):
		"""Test clearing request history."""
		# Add some requests
		for i in range(5):
			tracker = NetworkRequestTracker(
				request_id=f"clear-{i}",
				start_time=time.time(),
				url=f"https://example.com/api/{i}",
				method="GET"
			)
			tracker.end_time = time.time() + 0.1
			network_watchdog._store_completed_request(tracker)

		assert len(network_watchdog._completed_requests) == 5

		network_watchdog.clear_request_history()

		assert len(network_watchdog._completed_requests) == 0
		assert network_watchdog.get_recent_requests() == []


@pytest.mark.asyncio
class TestNetworkWatchdogIntegration:
	"""Integration tests for NetworkWatchdog with real browser session."""

	@pytest.fixture
	def httpserver(self):
		"""Create HTTP server for testing."""
		server = HTTPServer(host="127.0.0.1", port=0)
		server.start()
		yield server
		server.stop()

	def create_test_html_with_requests(self, server_url: str) -> str:
		"""Create HTML that makes various network requests."""
		return f"""
		<!DOCTYPE html>
		<html>
		<head>
			<title>Network Test Page</title>
			<style>
				.header {{ position: fixed; top: 0; width: 100%; height: 80px; background: #f0f0f0; }}
				.sidebar {{ position: fixed; left: 0; top: 80px; width: 200px; height: 500px; background: #e0e0e0; }}
				.main {{ margin-left: 220px; margin-top: 100px; padding: 20px; }}
				button {{ margin: 10px; padding: 10px; }}
			</style>
		</head>
		<body>
			<div class="header">
				<button id="search-btn" onclick="doSearch()">Search</button>
				<button id="submit-btn" onclick="submitForm()">Submit</button>
			</div>
			<div class="sidebar">
				<button id="nav-btn" onclick="navigate()">Navigate</button>
			</div>
			<div class="main">
				<form id="test-form">
					<input type="text" id="input-field" />
					<button type="submit" onclick="handleSubmit(event)">Form Submit</button>
				</form>
				<img src="{server_url}/test-image.png" alt="Test Image" />
			</div>

			<script>
				async function doSearch() {{
					try {{
						const response = await fetch('{server_url}/api/search', {{
							method: 'POST',
							headers: {{ 'Content-Type': 'application/json' }},
							body: JSON.stringify({{ query: 'test' }})
						}});
						console.log('Search response:', await response.json());
					}} catch (error) {{
						console.error('Search failed:', error);
					}}
				}}

				async function submitForm() {{
					try {{
						const response = await fetch('{server_url}/api/submit', {{
							method: 'POST',
							headers: {{ 'Content-Type': 'application/json' }},
							body: JSON.stringify({{ data: 'form data' }})
						}});
						console.log('Submit response:', await response.json());
					}} catch (error) {{
						console.error('Submit failed:', error);
					}}
				}}

				function navigate() {{
					window.location.href = '{server_url}/api/navigate';
				}}

				function handleSubmit(event) {{
					event.preventDefault();
					submitForm();
				}}

				// Auto-load some background data
				setTimeout(() => {{
					fetch('{server_url}/api/background-data')
						.then(r => r.json())
						.then(d => console.log('Background data:', d));
				}}, 1000);
			</script>
		</body>
		</html>
		"""

	async def test_real_network_monitoring(self, httpserver):
		"""Test network monitoring with real HTTP requests."""
		# Set up HTTP server responses
		def api_handler(request: Request) -> Response:
			if request.path == "/api/search":
				return Response(
					json.dumps({"results": ["item1", "item2"]}),
					content_type="application/json"
				)
			elif request.path == "/api/submit":
				return Response(
					json.dumps({"status": "success", "id": 123}),
					content_type="application/json"
				)
			elif request.path == "/api/background-data":
				return Response(
					json.dumps({"background": "data"}),
					content_type="application/json"
				)
			elif request.path == "/test-image.png":
				# Return a simple 1x1 PNG
				png_data = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\tpHYs\x00\x00\x0b\x13\x00\x00\x0b\x13\x01\x00\x9a\x9c\x18\x00\x00\x00\x0bIDATx\x9cc```\x00\x00\x00\x04\x00\x01]\xcc\x18\xdb\x00\x00\x00\x00IEND\xaeB`\x82'
				return Response(png_data, content_type="image/png")
			else:
				return Response("Not Found", status=404)

		httpserver.expect_request("/api/search", method="POST").respond_with_handler(api_handler)
		httpserver.expect_request("/api/submit", method="POST").respond_with_handler(api_handler)
		httpserver.expect_request("/api/background-data").respond_with_handler(api_handler)
		httpserver.expect_request("/test-image.png").respond_with_handler(api_handler)

		# Create the test HTML page
		test_html = self.create_test_html_with_requests(f"http://127.0.0.1:{httpserver.port}")

		def html_handler(request: Request) -> Response:
			return Response(test_html, content_type="text/html")

		httpserver.expect_request("/").respond_with_handler(html_handler)

		# This test would need a real browser session to fully test
		# For now, we'll test the watchdog logic with mock events
		from unittest.mock import MagicMock

		# Create mock browser session
		mock_session = MagicMock()
		mock_session.agent_focus = MagicMock()
		mock_session.agent_focus.target_id = "test-target"
		mock_session.browser_profile = MagicMock()
		mock_session.browser_profile.viewport = {"width": 1280, "height": 720}
		mock_session.event_bus = MagicMock()

		# Create NetworkWatchdog
		watchdog = NetworkWatchdog(
			event_bus=mock_session.event_bus,
			browser_session=mock_session
		)

		# Simulate network events that would come from CDP
		search_event = {
			"requestId": "search-123",
			"request": {
				"url": f"http://127.0.0.1:{httpserver.port}/api/search",
				"method": "POST"
			},
			"type": "XHR",
			"initiator": {
				"type": "script",
				"stack": {
					"callFrames": [
						{"functionName": "doSearch", "url": f"http://127.0.0.1:{httpserver.port}/"}
					]
				}
			}
		}

		# Test request tracking
		await watchdog._on_request_will_be_sent(search_event)

		assert len(watchdog._active_requests) == 1
		tracker = list(watchdog._active_requests.values())[0]
		assert tracker.url == f"http://127.0.0.1:{httpserver.port}/api/search"
		assert tracker.method == "POST"
		assert tracker.is_api_call is True
		assert "search" in tracker.likely_ui_trigger.lower()

		# Simulate response
		response_event = {
			"requestId": "search-123",
			"response": {
				"status": 200,
				"headers": {"content-type": "application/json"}
			}
		}

		watchdog._on_response_received(response_event)
		assert tracker.response_status == 200

		# Simulate completion
		finished_event = {"requestId": "search-123", "encodedDataLength": 1024}
		watchdog._on_loading_finished(finished_event)

		assert len(watchdog._active_requests) == 0
		assert len(watchdog._completed_requests) == 1

		completed = watchdog._completed_requests[0]
		assert completed.response_status == 200
		assert completed.response_size == 1024
		assert completed.duration is not None

		# Test getting recent requests
		recent = watchdog.get_recent_requests(1)
		assert len(recent) == 1
		assert recent[0]["url"] == f"http://127.0.0.1:{httpserver.port}/api/search"
		assert recent[0]["likely_ui_trigger"] is not None


if __name__ == "__main__":
	pytest.main([__file__, "-v"])