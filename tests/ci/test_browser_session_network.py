"""Tests for BrowserSession network monitoring integration."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from browser_use.browser.session import BrowserSession
from browser_use.browser.watchdogs.network_watchdog import NetworkRequestTracker, NetworkWatchdog


@pytest.mark.asyncio
class TestBrowserSessionNetworkIntegration:
	"""Test BrowserSession integration with NetworkWatchdog."""

	@pytest.fixture
	def mock_browser_session(self):
		"""Create a mock browser session with network watchdog."""
		from bubus import EventBus

		session = MagicMock(spec=BrowserSession)

		# Create a real NetworkWatchdog for testing
		session.event_bus = EventBus()
		session.agent_focus = MagicMock()
		session.agent_focus.target_id = "test-target-123"
		session.browser_profile = MagicMock()
		session.browser_profile.viewport = {"width": 1280, "height": 720}

		# Create and attach network watchdog
		network_watchdog = NetworkWatchdog(
			event_bus=session.event_bus,
			browser_session=session
		)
		session._network_watchdog = network_watchdog

		# Mock the actual methods we're testing
		session.get_network_requests = lambda *args, **kwargs: session._network_watchdog.get_recent_requests(*args, **kwargs) if session._network_watchdog else []
		session.get_network_summary = lambda: session._network_watchdog.get_requests_summary() if session._network_watchdog else {}
		session.get_user_triggered_requests = lambda *args, **kwargs: session._network_watchdog.get_user_triggered_requests(*args, **kwargs) if session._network_watchdog else []
		session.analyze_recent_user_activity = lambda *args, **kwargs: session._network_watchdog.analyze_recent_user_action(*args, **kwargs) if session._network_watchdog else {}
		session.get_requests_by_ui_section = lambda *args, **kwargs: session._network_watchdog.get_requests_by_ui_section(*args, **kwargs) if session._network_watchdog else []
		session.get_ui_activity_summary = lambda: session._network_watchdog.get_ui_section_summary() if session._network_watchdog else {}

		return session

	def add_test_requests_to_session(self, session):
		"""Add various test requests to the session's network watchdog."""
		watchdog = session._network_watchdog

		# API request from header search
		api_tracker = NetworkRequestTracker(
			request_id="api-search-1",
			start_time=time.time() - 10,
			url="https://example.com/api/search",
			method="POST",
			resource_type="XHR"
		)
		api_tracker.ui_section = "Header - Center (Navigation)"
		api_tracker.element_text = "Search button"
		api_tracker.response_status = 200
		api_tracker.end_time = time.time() - 9.5
		watchdog._store_completed_request(api_tracker)

		# Form submission from main content
		form_tracker = NetworkRequestTracker(
			request_id="form-submit-1",
			start_time=time.time() - 8,
			url="https://example.com/api/submit",
			method="POST",
			resource_type="XHR"
		)
		form_tracker.ui_section = "Main content - Center"
		form_tracker.element_text = "Submit button"
		form_tracker.response_status = 201
		form_tracker.end_time = time.time() - 7.5
		form_tracker.analyze_dom_context(None)  # This should set form submission trigger
		watchdog._store_completed_request(form_tracker)

		# Failed request from sidebar
		failed_tracker = NetworkRequestTracker(
			request_id="sidebar-fail-1",
			start_time=time.time() - 6,
			url="https://example.com/api/sidebar-action",
			method="DELETE",
			resource_type="XHR"
		)
		failed_tracker.ui_section = "Sidebar - Left (Navigation/Menu)"
		failed_tracker.element_text = "Delete button"
		failed_tracker.failed = True
		failed_tracker.failure_reason = "Network timeout"
		failed_tracker.end_time = time.time() - 5.5
		watchdog._store_completed_request(failed_tracker)

		# Image resource
		image_tracker = NetworkRequestTracker(
			request_id="image-1",
			start_time=time.time() - 4,
			url="https://example.com/images/logo.png",
			method="GET",
			resource_type="Image"
		)
		image_tracker.ui_section = "Header - Left (Logo/Menu)"
		image_tracker.response_status = 200
		image_tracker.end_time = time.time() - 3.8
		watchdog._store_completed_request(image_tracker)

		# Background API call
		background_tracker = NetworkRequestTracker(
			request_id="background-1",
			start_time=time.time() - 2,
			url="https://example.com/api/background-sync",
			method="GET",
			resource_type="XHR"
		)
		background_tracker.ui_section = "Background process"
		background_tracker.response_status = 200
		background_tracker.end_time = time.time() - 1.8
		watchdog._store_completed_request(background_tracker)

	def test_get_network_requests_basic(self, mock_browser_session):
		"""Test basic network request retrieval."""
		self.add_test_requests_to_session(mock_browser_session)

		# Test getting all recent requests
		requests = mock_browser_session.get_network_requests(limit=10)
		assert len(requests) == 5
		assert all(isinstance(req, dict) for req in requests)

		# Test limit functionality
		limited_requests = mock_browser_session.get_network_requests(limit=3)
		assert len(limited_requests) == 3

	def test_get_network_requests_by_type(self, mock_browser_session):
		"""Test filtering network requests by type."""
		self.add_test_requests_to_session(mock_browser_session)

		# Test API requests filter
		api_requests = mock_browser_session.get_network_requests(limit=10, request_type='api')
		assert len(api_requests) == 4  # 4 XHR requests
		assert all(req['resource_type'] == 'XHR' for req in api_requests)

		# Test UI resources filter
		ui_requests = mock_browser_session.get_network_requests(limit=10, request_type='ui')
		assert len(ui_requests) == 1  # 1 Image request
		assert ui_requests[0]['resource_type'] == 'Image'

		# Test failed requests filter
		failed_requests = mock_browser_session.get_network_requests(limit=10, request_type='failed')
		assert len(failed_requests) == 1
		assert failed_requests[0]['failed'] is True

	def test_get_network_summary(self, mock_browser_session):
		"""Test network activity summary."""
		self.add_test_requests_to_session(mock_browser_session)

		summary = mock_browser_session.get_network_summary()

		assert summary['total_completed'] == 5
		assert summary['api_requests'] == 4  # XHR requests
		assert summary['failed_requests'] == 1
		assert summary['success_rate'] == 80.0  # 4 out of 5 succeeded

	def test_get_user_triggered_requests(self, mock_browser_session):
		"""Test filtering user-triggered requests."""
		self.add_test_requests_to_session(mock_browser_session)

		user_requests = mock_browser_session.get_user_triggered_requests(limit=10)

		# Should include search and form submission (both have user interaction patterns)
		assert len(user_requests) >= 1
		# At least one should be a form submission
		form_requests = [req for req in user_requests if 'submit' in req.get('url', '').lower()]
		assert len(form_requests) >= 1

	def test_analyze_recent_user_activity(self, mock_browser_session):
		"""Test recent user activity analysis."""
		self.add_test_requests_to_session(mock_browser_session)

		analysis = mock_browser_session.analyze_recent_user_activity(seconds_back=30)

		assert 'time_window_seconds' in analysis
		assert analysis['time_window_seconds'] == 30
		assert analysis['total_requests'] == 5
		assert analysis['failed_requests'] == 1
		assert isinstance(analysis['recent_user_actions'], list)
		assert isinstance(analysis['recent_api_calls'], list)

	def test_get_requests_by_ui_section(self, mock_browser_session):
		"""Test filtering requests by UI section."""
		self.add_test_requests_to_session(mock_browser_session)

		# Test header requests
		header_requests = mock_browser_session.get_requests_by_ui_section('header')
		assert len(header_requests) == 2  # Search from header-center + logo from header-left

		# Test sidebar requests
		sidebar_requests = mock_browser_session.get_requests_by_ui_section('sidebar')
		assert len(sidebar_requests) == 1
		assert sidebar_requests[0]['failed'] is True

		# Test main content requests
		main_requests = mock_browser_session.get_requests_by_ui_section('main')
		assert len(main_requests) == 1
		assert 'submit' in main_requests[0]['url'].lower()

	def test_get_ui_activity_summary(self, mock_browser_session):
		"""Test UI activity summary."""
		self.add_test_requests_to_session(mock_browser_session)

		summary = mock_browser_session.get_ui_activity_summary()

		assert 'total_sections' in summary
		assert 'section_breakdown' in summary
		assert 'most_active_section' in summary

		# Should have multiple sections
		assert summary['total_sections'] >= 4

		# Should have breakdown of requests per section
		breakdown = summary['section_breakdown']
		assert 'Header - Center (Navigation)' in breakdown
		assert 'Main content - Center' in breakdown
		assert 'Sidebar - Left (Navigation/Menu)' in breakdown

	def test_network_watchdog_disabled(self):
		"""Test behavior when network watchdog is not available."""
		session = MagicMock(spec=BrowserSession)
		session._network_watchdog = None

		# Mock the methods to handle None watchdog
		session.get_network_requests = lambda *args, **kwargs: [] if not session._network_watchdog else session._network_watchdog.get_recent_requests(*args, **kwargs)
		session.get_network_summary = lambda: {'total_completed': 0, 'api_requests': 0, 'failed_requests': 0, 'active_requests': 0, 'success_rate': 0} if not session._network_watchdog else session._network_watchdog.get_requests_summary()

		requests = session.get_network_requests()
		assert requests == []

		summary = session.get_network_summary()
		assert summary['total_completed'] == 0
		assert summary['success_rate'] == 0

	def test_empty_request_history(self, mock_browser_session):
		"""Test behavior with empty request history."""
		# Don't add any requests

		requests = mock_browser_session.get_network_requests()
		assert requests == []

		summary = mock_browser_session.get_network_summary()
		assert summary['total_completed'] == 0

		user_requests = mock_browser_session.get_user_triggered_requests()
		assert user_requests == []

		analysis = mock_browser_session.analyze_recent_user_activity()
		assert analysis['total_requests'] == 0
		assert analysis['recent_user_actions'] == []

	def test_request_data_structure(self, mock_browser_session):
		"""Test that returned request data has the expected structure."""
		self.add_test_requests_to_session(mock_browser_session)

		requests = mock_browser_session.get_network_requests(limit=1)
		assert len(requests) == 1

		request = requests[0]

		# Verify essential fields are present
		essential_fields = [
			'request_id', 'url', 'method', 'resource_type',
			'start_time', 'end_time', 'duration', 'response_status',
			'failed', 'is_api_call', 'is_ui_resource',
			'ui_section', 'element_text', 'likely_ui_trigger'
		]

		for field in essential_fields:
			assert field in request, f"Missing field: {field}"

		# Verify data types
		assert isinstance(request['request_id'], str)
		assert isinstance(request['url'], str)
		assert isinstance(request['method'], str)
		assert isinstance(request['is_api_call'], bool)
		assert isinstance(request['is_ui_resource'], bool)
		assert isinstance(request['failed'], bool)

		if request['duration'] is not None:
			assert isinstance(request['duration'], (int, float))

	def test_performance_with_many_requests(self, mock_browser_session):
		"""Test performance and limits with many requests."""
		watchdog = mock_browser_session._network_watchdog

		# Add many requests to test storage limits
		for i in range(250):
			tracker = NetworkRequestTracker(
				request_id=f"perf-test-{i}",
				start_time=time.time() - (250 - i),
				url=f"https://example.com/api/test/{i}",
				method="GET",
				resource_type="XHR" if i % 3 == 0 else "Document"
			)
			tracker.ui_section = f"Section-{i % 5}"  # 5 different sections
			tracker.response_status = 200 if i % 10 != 9 else 500  # 10% failure rate
			tracker.failed = i % 10 == 9
			tracker.end_time = time.time() - (250 - i - 0.1)
			watchdog._store_completed_request(tracker)

		# Test that storage limit is respected
		assert len(watchdog._completed_requests) == 200  # max_stored_requests

		# Test that recent requests work efficiently
		recent = mock_browser_session.get_network_requests(limit=10)
		assert len(recent) == 10

		# Test that filtering still works
		api_requests = mock_browser_session.get_network_requests(limit=50, request_type='api')
		assert len(api_requests) <= 50

		# Test UI summary with many sections
		summary = mock_browser_session.get_ui_activity_summary()
		assert summary['total_sections'] == 5
		assert sum(summary['section_breakdown'].values()) == 200


if __name__ == "__main__":
	pytest.main([__file__, "-v"])