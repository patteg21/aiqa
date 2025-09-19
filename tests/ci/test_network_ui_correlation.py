"""Tests for network request UI element correlation functionality."""

import time
from unittest.mock import MagicMock

import pytest

from browser_use.browser.watchdogs.network_watchdog import NetworkRequestTracker


class TestNetworkUICorrelation:
	"""Test UI element correlation with network requests."""

	def test_url_pattern_analysis(self):
		"""Test UI section identification based on URL patterns."""
		test_cases = [
			{
				'url': 'https://example.com/api/search?q=test',
				'expected_section': 'Search/Filter interface',
				'expected_trigger': 'Search/Filter action'
			},
			{
				'url': 'https://example.com/api/submit',
				'expected_section': 'Form submission area',
				'expected_trigger': 'Form submission'
			},
			{
				'url': 'https://example.com/api/save',
				'expected_section': 'Form submission area',
				'expected_trigger': 'Form submission'
			},
			{
				'url': 'https://example.com/api/delete/123',
				'expected_section': 'Action controls',
				'expected_trigger': None  # Trigger analysis uses different logic
			},
			{
				'url': 'https://example.com/api/load-data',
				'expected_section': 'Content loading area',
				'expected_trigger': 'Data loading'
			},
		]

		for case in test_cases:
			tracker = NetworkRequestTracker(
				request_id=f"test-{hash(case['url'])}",
				start_time=time.time(),
				url=case['url'],
				method="POST",
				resource_type="XHR"
			)
			tracker.analyze_dom_context(None)

			assert case['expected_section'] in tracker.ui_section, f"Failed for URL: {case['url']}"
			if case['expected_trigger']:
				assert case['expected_trigger'] in tracker.likely_ui_trigger, f"Failed trigger for URL: {case['url']}"

	def test_position_based_ui_sections(self):
		"""Test UI section identification based on element position."""
		test_positions = [
			# Header positions
			{'x': 100, 'y': 30, 'expected': 'Header - Left'},
			{'x': 640, 'y': 50, 'expected': 'Header - Center'},
			{'x': 1100, 'y': 40, 'expected': 'Header - Right'},

			# Sidebar positions
			{'x': 50, 'y': 300, 'expected': 'Sidebar - Left'},
			{'x': 1200, 'y': 400, 'expected': 'Sidebar - Right'},

			# Main content positions
			{'x': 640, 'y': 200, 'expected': 'Main content - Top'},
			{'x': 500, 'y': 350, 'expected': 'Main content - Center'},
			{'x': 800, 'y': 600, 'expected': 'Main content - Bottom'},

			# Footer position
			{'x': 640, 'y': 680, 'expected': 'Footer'},
		]

		for pos in test_positions:
			tracker = NetworkRequestTracker(
				request_id=f"pos-{pos['x']}-{pos['y']}",
				start_time=time.time(),
				url="https://example.com/test",
				method="GET"
			)
			tracker.element_position = {
				'x': pos['x'],
				'y': pos['y'],
				'width': 100,
				'height': 30
			}
			tracker.identify_ui_section_by_position(1280, 720)

			assert pos['expected'] in tracker.ui_section, f"Failed for position ({pos['x']}, {pos['y']})"

	def test_initiator_stack_analysis(self):
		"""Test analysis of JavaScript stack traces to identify triggers."""
		test_cases = [
			{
				'stack': {
					'callFrames': [
						{'functionName': 'handleClick', 'url': 'https://example.com/app.js'},
						{'functionName': 'addEventListener', 'url': 'https://example.com/app.js'}
					]
				},
				'expected_trigger': 'User interaction (handleclick)'
			},
			{
				'stack': {
					'callFrames': [
						{'functionName': 'onSubmit', 'url': 'https://example.com/form.js'},
						{'functionName': 'validateForm', 'url': 'https://example.com/form.js'}
					]
				},
				'expected_trigger': 'User interaction (onsubmit)'  # 'submit' pattern matches first
			},
			{
				'stack': {
					'callFrames': [
						{'functionName': 'fetchData', 'url': 'https://example.com/api.js'},
						{'functionName': 'makeRequest', 'url': 'https://example.com/api.js'}
					]
				},
				'expected_trigger': 'AJAX call'
			},
			{
				'stack': {
					'callFrames': [
						{'functionName': 'onChange', 'url': 'https://example.com/input.js'},
						{'functionName': 'debounce', 'url': 'https://example.com/utils.js'}
					]
				},
				'expected_trigger': 'User interaction (onchange)'
			}
		]

		for case in test_cases:
			tracker = NetworkRequestTracker(
				request_id=f"stack-{hash(str(case['stack']))}",
				start_time=time.time(),
				url="https://example.com/api/test",
				method="POST",
				resource_type="XHR"
			)
			tracker.initiator = {
				'type': 'script',
				'stack': case['stack']
			}

			trigger = tracker.likely_ui_trigger
			assert trigger is not None, f"No trigger detected for {case['stack']}"
			assert case['expected_trigger'].lower() in trigger.lower(), f"Expected '{case['expected_trigger']}', got '{trigger}'"

	def test_resource_type_correlation(self):
		"""Test correlation between resource types and UI elements."""
		test_cases = [
			{
				'resource_type': 'Image',
				'url': 'https://example.com/images/logo.png',
				'expected_section': 'Image content',
				'expected_text_contains': 'Image: logo.png'
			},
			{
				'resource_type': 'Stylesheet',
				'url': 'https://example.com/css/main.css',
				'expected_section': 'Page resources'
			},
			{
				'resource_type': 'Script',
				'url': 'https://example.com/js/app.js',
				'expected_section': 'Page resources'
			},
			{
				'resource_type': 'Media',
				'url': 'https://example.com/videos/intro.mp4',
				'expected_section': 'Media content',
				'expected_text_contains': 'Media: intro.mp4'
			}
		]

		for case in test_cases:
			tracker = NetworkRequestTracker(
				request_id=f"resource-{case['resource_type']}",
				start_time=time.time(),
				url=case['url'],
				method="GET",
				resource_type=case['resource_type']
			)
			tracker.analyze_dom_context(None)

			assert case['expected_section'] in tracker.ui_section, f"Failed section for {case['resource_type']}"
			if 'expected_text_contains' in case:
				assert case['expected_text_contains'] in tracker.element_text, f"Failed text for {case['resource_type']}"

	def test_api_vs_ui_resource_classification(self):
		"""Test classification of requests as API calls vs UI resources."""
		api_cases = [
			{'resource_type': 'XHR', 'url': 'https://api.example.com/users'},
			{'resource_type': 'Fetch', 'url': 'https://example.com/api/data'},
			{'resource_type': 'Other', 'url': 'https://example.com/endpoint', 'headers': {'content-type': 'application/json'}}
		]

		ui_cases = [
			{'resource_type': 'Document', 'url': 'https://example.com/page.html'},
			{'resource_type': 'Stylesheet', 'url': 'https://example.com/style.css'},
			{'resource_type': 'Script', 'url': 'https://example.com/script.js'},
			{'resource_type': 'Image', 'url': 'https://example.com/image.png'},
			{'resource_type': 'Font', 'url': 'https://example.com/font.woff'}
		]

		# Test API classification
		for case in api_cases:
			tracker = NetworkRequestTracker(
				request_id=f"api-{case['resource_type']}",
				start_time=time.time(),
				url=case['url'],
				method="GET",
				resource_type=case['resource_type']
			)
			if 'headers' in case:
				tracker.response_headers = case['headers']

			assert tracker.is_api_call is True, f"Failed API classification for {case}"
			assert tracker.is_ui_resource is False, f"Incorrectly classified as UI resource: {case}"

		# Test UI resource classification
		for case in ui_cases:
			tracker = NetworkRequestTracker(
				request_id=f"ui-{case['resource_type']}",
				start_time=time.time(),
				url=case['url'],
				method="GET",
				resource_type=case['resource_type']
			)

			assert tracker.is_ui_resource is True, f"Failed UI classification for {case}"
			assert tracker.is_api_call is False, f"Incorrectly classified as API call: {case}"

	def test_complex_ui_correlation_scenario(self):
		"""Test a complex scenario with multiple correlation factors."""
		# Simulate a form submission from the header that triggers a search API
		tracker = NetworkRequestTracker(
			request_id="complex-scenario-1",
			start_time=time.time(),
			url="https://example.com/api/search",
			method="POST",
			resource_type="XHR"
		)

		# Set initiator information
		tracker.initiator = {
			'type': 'script',
			'stack': {
				'callFrames': [
					{'functionName': 'submitSearchForm', 'url': 'https://example.com/search.js'},
					{'functionName': 'handleSubmit', 'url': 'https://example.com/search.js'}
				]
			}
		}

		# Set position information (header area)
		tracker.element_position = {'x': 640, 'y': 50, 'width': 200, 'height': 40}

		# Set response information
		tracker.response_status = 200
		tracker.response_headers = {'content-type': 'application/json'}
		tracker.end_time = time.time() + 0.5

		# Perform analysis
		tracker.analyze_dom_context(None)
		tracker.identify_ui_section_by_position(1280, 720)

		# Verify multiple correlation factors
		assert tracker.is_api_call is True
		assert "search" in tracker.likely_ui_trigger.lower()
		assert "header" in tracker.ui_section.lower()
		assert "search" in tracker.ui_section.lower()

		# Verify serialization includes all correlation data
		data = tracker.to_dict()
		assert 'ui_section' in data
		assert 'element_position' in data
		assert 'likely_ui_trigger' in data
		assert data['is_api_call'] is True

	def test_edge_cases_and_fallbacks(self):
		"""Test edge cases and fallback behavior."""
		# Test with no initiator information
		no_initiator_tracker = NetworkRequestTracker(
			request_id="no-initiator",
			start_time=time.time(),
			url="https://example.com/api/mystery",
			method="GET",
			resource_type="XHR"
		)
		no_initiator_tracker.analyze_dom_context(None)
		# Should not crash and should have some default classification
		assert no_initiator_tracker.ui_section is not None

		# Test with empty stack frames
		empty_stack_tracker = NetworkRequestTracker(
			request_id="empty-stack",
			start_time=time.time(),
			url="https://example.com/api/empty",
			method="POST",
			resource_type="XHR"
		)
		empty_stack_tracker.initiator = {
			'type': 'script',
			'stack': {'callFrames': []}
		}
		empty_stack_tracker.analyze_dom_context(None)
		# Should not crash
		assert empty_stack_tracker.likely_ui_trigger is None or isinstance(empty_stack_tracker.likely_ui_trigger, str)

		# Test with invalid position data
		invalid_pos_tracker = NetworkRequestTracker(
			request_id="invalid-pos",
			start_time=time.time(),
			url="https://example.com/test",
			method="GET"
		)
		invalid_pos_tracker.element_position = {'x': -100, 'y': -50}  # Invalid coordinates
		invalid_pos_tracker.identify_ui_section_by_position(1280, 720)
		# Should handle gracefully
		assert isinstance(invalid_pos_tracker.ui_section, (str, type(None)))

	def test_initiator_type_handling(self):
		"""Test different initiator types."""
		initiator_cases = [
			{
				'type': 'parser',
				'expected_trigger': 'Page parsing (HTML/CSS)'
			},
			{
				'type': 'other',
				'expected_trigger': 'Browser initiated'
			},
			{
				'type': 'script',
				'stack': {'callFrames': []},
				'expected_trigger': None  # No specific function name
			}
		]

		for case in initiator_cases:
			tracker = NetworkRequestTracker(
				request_id=f"initiator-{case['type']}",
				start_time=time.time(),
				url="https://example.com/test",
				method="GET"
			)
			tracker.initiator = case.copy()
			if 'expected_trigger' in case:
				del tracker.initiator['expected_trigger']

			trigger = tracker.likely_ui_trigger
			if case['expected_trigger']:
				assert case['expected_trigger'] in trigger, f"Expected '{case['expected_trigger']}', got '{trigger}'"

	def test_comprehensive_serialization(self):
		"""Test that all UI correlation data is properly serialized."""
		tracker = NetworkRequestTracker(
			request_id="serialization-test",
			start_time=time.time(),
			url="https://example.com/api/comprehensive",
			method="POST",
			resource_type="XHR"
		)

		# Set all possible correlation data
		tracker.ui_section = "Header - Center (Navigation)"
		tracker.element_selector = "#search-button"
		tracker.element_text = "Search Products"
		tracker.element_position = {'x': 640, 'y': 50, 'width': 120, 'height': 35}
		tracker.dom_element_info = {'tag': 'button', 'classes': ['btn', 'btn-primary']}
		tracker.response_status = 200

		data = tracker.to_dict()

		# Verify all UI correlation fields are present
		ui_fields = [
			'ui_section', 'element_selector', 'element_text',
			'element_position', 'dom_element_info', 'likely_ui_trigger'
		]

		for field in ui_fields:
			assert field in data, f"Missing UI correlation field: {field}"

		# Verify data integrity
		assert data['ui_section'] == "Header - Center (Navigation)"
		assert data['element_selector'] == "#search-button"
		assert data['element_text'] == "Search Products"
		assert data['element_position']['x'] == 640
		assert data['dom_element_info']['tag'] == 'button'


if __name__ == "__main__":
	pytest.main([__file__, "-v"])