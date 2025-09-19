"""Network request monitoring watchdog for tracking browser network activity."""

import asyncio
import time
from typing import TYPE_CHECKING, ClassVar

from bubus import BaseEvent
from cdp_use.cdp.target import SessionID, TargetID
from pydantic import Field, PrivateAttr

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserStoppedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	pass


class NetworkRequestTracker:
	"""Tracks ongoing network requests with detailed information."""

	def __init__(self, request_id: str, start_time: float, url: str, method: str, resource_type: str | None = None):
		self.request_id = request_id
		self.start_time = start_time
		self.url = url
		self.method = method
		self.resource_type = resource_type
		self.response_status: int | None = None
		self.response_headers: dict[str, str] = {}
		self.response_body: str | None = None
		self.end_time: float | None = None
		self.failed: bool = False
		self.failure_reason: str | None = None
		self.initiator: dict | None = None  # What triggered this request
		self.response_size: int | None = None

		# DOM correlation information
		self.dom_element_info: dict | None = None  # Captured DOM element data
		self.ui_section: str | None = None  # Identified UI section (header, sidebar, main, etc.)
		self.element_selector: str | None = None  # CSS selector for the element
		self.element_text: str | None = None  # Visible text of the element
		self.element_position: dict | None = None  # Position and bounds of element

	@property
	def duration(self) -> float | None:
		"""Get request duration in seconds."""
		if self.end_time:
			return self.end_time - self.start_time
		return None

	@property
	def is_api_call(self) -> bool:
		"""Check if this looks like an API call (XHR/Fetch with JSON)."""
		return self.resource_type in ['XHR', 'Fetch'] or (
			self.response_headers.get('content-type', '').startswith('application/json')
		)

	@property
	def is_ui_resource(self) -> bool:
		"""Check if this is a UI-related resource (HTML, CSS, JS, images)."""
		return self.resource_type in ['Document', 'Stylesheet', 'Script', 'Image', 'Font']

	@property
	def likely_ui_trigger(self) -> str | None:
		"""Analyze the request to determine what UI element likely triggered it."""
		# First check initiator information if available
		if self.initiator:
			initiator_type = self.initiator.get('type', '')

			# Check if triggered by user action
			if initiator_type == 'script':
				# Look for common user interaction patterns in the stack
				stack = self.initiator.get('stack', {})
				call_frames = stack.get('callFrames', []) if stack else []

				for frame in call_frames:
					function_name = frame.get('functionName', '').lower()
					url = frame.get('url', '')

					# Common UI interaction patterns
					if any(pattern in function_name for pattern in ['click', 'submit', 'change', 'input']):
						return f"User interaction ({function_name})"
					if 'onclick' in function_name or 'onsubmit' in function_name:
						return f"Event handler ({function_name})"
					if 'fetch' in function_name or 'xhr' in function_name:
						return "AJAX call"

			elif initiator_type == 'parser':
				return "Page parsing (HTML/CSS)"
			elif initiator_type == 'other':
				return "Browser initiated"

		# Check URL patterns for common API endpoints (even without initiator)
		if self.is_api_call:
			if any(pattern in self.url.lower() for pattern in ['/submit', '/save', '/update', '/delete']):
				return "Form submission"
			elif any(pattern in self.url.lower() for pattern in ['/search', '/query', '/filter']):
				return "Search/Filter action"
			elif any(pattern in self.url.lower() for pattern in ['/load', '/get', '/fetch']):
				return "Data loading"

		return None

	def analyze_dom_context(self, dom_snapshot: dict | None = None) -> None:
		"""Analyze DOM context to identify the UI element that triggered this request."""
		# Always try basic correlation based on request type and URL patterns
		if self.is_api_call:
			self._identify_interactive_elements(dom_snapshot)
		elif self.resource_type in ['Image', 'Media']:
			self._identify_media_elements(dom_snapshot)
		elif self.resource_type in ['Stylesheet', 'Script']:
			self.ui_section = "Page resources"

		# If we have initiator and DOM info, do more detailed analysis
		if self.initiator and dom_snapshot:
			# Extract information from the initiator stack
			stack = self.initiator.get('stack', {})
			call_frames = stack.get('callFrames', []) if stack else []

			# Look for DOM event information in the stack
			for frame in call_frames:
				url = frame.get('url', '')
				line_number = frame.get('lineNumber', 0)
				column_number = frame.get('columnNumber', 0)

				# If this frame is from the main document, try to correlate with DOM
				if url and not url.startswith('chrome-extension://') and 'javascript:' not in url:
					self._correlate_with_dom_elements(dom_snapshot, url, line_number)
					break

	def _correlate_with_dom_elements(self, dom_snapshot: dict, source_url: str, line_number: int) -> None:
		"""Correlate request with specific DOM elements."""
		# This is a simplified correlation - in practice, you'd need more sophisticated analysis
		# For now, we'll identify common UI patterns based on the request characteristics

		if self.is_api_call:
			# Look for form elements, buttons, or interactive elements
			self._identify_interactive_elements(dom_snapshot)
		elif self.resource_type in ['Image', 'Media']:
			# Look for img, video, or media elements
			self._identify_media_elements(dom_snapshot)
		elif self.resource_type in ['Stylesheet', 'Script']:
			# These are usually loaded by the page structure
			self.ui_section = "Page resources"

	def _identify_interactive_elements(self, dom_snapshot: dict) -> None:
		"""Identify likely interactive elements that could trigger API calls."""
		# Common patterns for elements that trigger API calls
		common_triggers = [
			{'type': 'button', 'section': 'Action button'},
			{'type': 'form', 'section': 'Form submission'},
			{'type': 'input[type="submit"]', 'section': 'Submit button'},
			{'type': 'a', 'section': 'Link'},
		]

		# Analyze URL patterns to guess the triggering element
		url_lower = self.url.lower()
		if any(pattern in url_lower for pattern in ['/search', '/query', '/filter']):
			self.ui_section = "Search/Filter interface"
			self.element_text = "Search or filter control"
		elif any(pattern in url_lower for pattern in ['/submit', '/save', '/create', '/update']):
			self.ui_section = "Form submission area"
			self.element_text = "Submit or save button"
		elif any(pattern in url_lower for pattern in ['/delete', '/remove']):
			self.ui_section = "Action controls"
			self.element_text = "Delete or remove button"
		elif any(pattern in url_lower for pattern in ['/load', '/get', '/fetch']):
			self.ui_section = "Content loading area"
			self.element_text = "Dynamic content trigger"
		else:
			self.ui_section = "Interactive element"

	def _identify_media_elements(self, dom_snapshot: dict) -> None:
		"""Identify media elements in the DOM."""
		if self.resource_type == 'Image':
			self.ui_section = "Image content"
			self.element_text = f"Image: {self.url.split('/')[-1]}"
		elif self.resource_type in ['Media', 'Other']:
			self.ui_section = "Media content"
			self.element_text = f"Media: {self.url.split('/')[-1]}"

	def identify_ui_section_by_position(self, viewport_width: int = 1280, viewport_height: int = 720) -> None:
		"""Identify UI section based on element position (if available)."""
		if not self.element_position:
			return

		x = self.element_position.get('x', 0)
		y = self.element_position.get('y', 0)
		width = self.element_position.get('width', 0)
		height = self.element_position.get('height', 0)

		# Common UI layout patterns
		if y < 100:  # Top of page
			if x < viewport_width * 0.2:
				self.ui_section = "Header - Left (Logo/Menu)"
			elif x > viewport_width * 0.8:
				self.ui_section = "Header - Right (User/Actions)"
			else:
				self.ui_section = "Header - Center (Navigation)"
		elif x < 200:  # Left side
			self.ui_section = "Sidebar - Left (Navigation/Menu)"
		elif x > viewport_width - 200:  # Right side
			self.ui_section = "Sidebar - Right (Info/Actions)"
		elif y > viewport_height - 100:  # Bottom
			self.ui_section = "Footer"
		else:  # Center area
			if y < viewport_height * 0.3:
				self.ui_section = "Main content - Top"
			elif y > viewport_height * 0.7:
				self.ui_section = "Main content - Bottom"
			else:
				self.ui_section = "Main content - Center"

	def to_dict(self) -> dict:
		"""Convert to dictionary for serialization."""
		return {
			'request_id': self.request_id,
			'url': self.url,
			'method': self.method,
			'resource_type': self.resource_type,
			'start_time': self.start_time,
			'end_time': self.end_time,
			'duration': self.duration,
			'response_status': self.response_status,
			'response_headers': self.response_headers,
			'failed': self.failed,
			'failure_reason': self.failure_reason,
			'initiator': self.initiator,
			'response_size': self.response_size,
			'is_api_call': self.is_api_call,
			'is_ui_resource': self.is_ui_resource,
			'likely_ui_trigger': self.likely_ui_trigger,
			# DOM correlation data
			'ui_section': self.ui_section,
			'element_selector': self.element_selector,
			'element_text': self.element_text,
			'element_position': self.element_position,
			'dom_element_info': self.dom_element_info,
		}


class NetworkWatchdog(BaseWatchdog):
	"""Monitors network requests and responses for agent analysis."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserConnectedEvent,
		BrowserStoppedEvent,
		TabCreatedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = []

	# Configuration
	max_stored_requests: int = Field(default=200)
	enable_response_body_capture: bool = Field(default=False)  # Expensive, use sparingly
	api_patterns: list[str] = Field(default_factory=lambda: ['/api/', '/graphql', '.json'])

	# Private state
	_active_requests: dict[str, NetworkRequestTracker] = PrivateAttr(default_factory=dict)
	_completed_requests: list[NetworkRequestTracker] = PrivateAttr(default_factory=list)
	_cdp_event_tasks: set[asyncio.Task] = PrivateAttr(default_factory=set)
	_sessions_with_listeners: set[str] = PrivateAttr(default_factory=set)

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Start network monitoring when browser connects."""
		self.logger.info('[NetworkWatchdog] 🌐 Network monitoring enabled')

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Clean up when browser stops."""
		await self._cleanup_monitoring()

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Attach network monitoring to new tab."""
		assert self.browser_session.agent_focus is not None, 'No current target ID'
		await self.attach_to_target(self.browser_session.agent_focus.target_id)

	async def attach_to_target(self, target_id: TargetID) -> None:
		"""Set up network monitoring for a specific target using CDP."""
		try:
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Check if we already have listeners for this session
			if cdp_session.session_id in self._sessions_with_listeners:
				self.logger.debug(f'[NetworkWatchdog] Already monitoring session: {cdp_session.session_id}')
				return

			# Enable Network domain for monitoring
			await cdp_session.cdp_client.send.Network.enable(session_id=cdp_session.session_id)

			# Set up network event handlers
			def on_request_will_be_sent(event, session_id=None):
				task = asyncio.create_task(self._on_request_will_be_sent(event))
				self._cdp_event_tasks.add(task)
				task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

			def on_response_received(event, session_id=None):
				self._on_response_received(event)

			def on_loading_failed(event, session_id=None):
				self._on_loading_failed(event)

			def on_loading_finished(event, session_id=None):
				self._on_loading_finished(event)

			# Register event handlers
			cdp_session.cdp_client.register.Network.requestWillBeSent(on_request_will_be_sent)
			cdp_session.cdp_client.register.Network.responseReceived(on_response_received)
			cdp_session.cdp_client.register.Network.loadingFailed(on_loading_failed)
			cdp_session.cdp_client.register.Network.loadingFinished(on_loading_finished)

			# Track that we've added listeners to this session
			self._sessions_with_listeners.add(cdp_session.session_id)

			# Get target info for logging
			targets = await cdp_session.cdp_client.send.Target.getTargets()
			target_info = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)
			if target_info:
				self.logger.debug(f'[NetworkWatchdog] Monitoring network for: {target_info.get("url", "unknown")}')

		except Exception as e:
			self.logger.warning(f'[NetworkWatchdog] Failed to attach to target {target_id}: {e}')

	async def _on_request_will_be_sent(self, event: dict) -> None:
		"""Track new network request from CDP event."""
		request_id = event.get('requestId', '')
		request = event.get('request', {})

		tracker = NetworkRequestTracker(
			request_id=request_id,
			start_time=time.time(),
			url=request.get('url', ''),
			method=request.get('method', ''),
			resource_type=event.get('type'),
		)
		tracker.initiator = event.get('initiator', {})

		# Perform DOM correlation analysis
		await self._analyze_dom_correlation(tracker)

		self._active_requests[request_id] = tracker

		# Enhanced logging with DOM context
		dom_info = f" [{tracker.ui_section}]" if tracker.ui_section else ""
		if tracker.is_api_call:
			self.logger.info(f'[NetworkWatchdog] 🔄 API {tracker.method} {tracker.url[:60]}...{dom_info}')
		else:
			self.logger.debug(f'[NetworkWatchdog] 🌐 {tracker.method} {tracker.url[:60]}... ({tracker.resource_type}){dom_info}')

	def _on_response_received(self, event: dict) -> None:
		"""Update request with response data."""
		request_id = event.get('requestId', '')
		if request_id in self._active_requests:
			tracker = self._active_requests[request_id]
			response = event.get('response', {})
			tracker.response_status = response.get('status')
			tracker.response_headers = response.get('headers', {})

			elapsed = time.time() - tracker.start_time
			status_emoji = "✅" if tracker.response_status and tracker.response_status < 400 else "❌"

			if tracker.is_api_call:
				self.logger.info(f'[NetworkWatchdog] {status_emoji} {tracker.response_status} API {tracker.url[:60]}... ({elapsed:.2f}s)')
			else:
				self.logger.debug(f'[NetworkWatchdog] {status_emoji} {tracker.response_status} {tracker.url[:60]}... ({elapsed:.2f}s)')

	def _on_loading_failed(self, event: dict) -> None:
		"""Handle request failure."""
		request_id = event.get('requestId', '')
		if request_id in self._active_requests:
			tracker = self._active_requests[request_id]
			tracker.failed = True
			tracker.failure_reason = event.get('errorText', 'Unknown error')
			tracker.end_time = time.time()

			self.logger.warning(f'[NetworkWatchdog] ❌ FAILED {tracker.url[:60]}... ({tracker.failure_reason})')
			self._store_completed_request(tracker)
			del self._active_requests[request_id]

	def _on_loading_finished(self, event: dict) -> None:
		"""Complete request tracking when loading is finished."""
		request_id = event.get('requestId', '')
		if request_id in self._active_requests:
			tracker = self._active_requests[request_id]
			tracker.end_time = time.time()

			# Get response size if available
			encoded_data_length = event.get('encodedDataLength')
			if encoded_data_length:
				tracker.response_size = encoded_data_length

			self._store_completed_request(tracker)
			del self._active_requests[request_id]

	def _store_completed_request(self, tracker: NetworkRequestTracker) -> None:
		"""Store completed request and maintain size limit."""
		self._completed_requests.append(tracker)
		# Keep only the most recent requests
		if len(self._completed_requests) > self.max_stored_requests:
			self._completed_requests = self._completed_requests[-self.max_stored_requests:]

	async def _cleanup_monitoring(self) -> None:
		"""Clean up monitoring resources."""
		# Cancel all CDP event handler tasks
		for task in list(self._cdp_event_tasks):
			if not task.done():
				task.cancel()
		# Wait for all tasks to complete cancellation
		if self._cdp_event_tasks:
			await asyncio.gather(*self._cdp_event_tasks, return_exceptions=True)
		self._cdp_event_tasks.clear()

		# Clear tracking
		self._active_requests.clear()
		self._sessions_with_listeners.clear()
		self.logger.debug('[NetworkWatchdog] Network monitoring cleaned up')

	# Public API for agent access
	def get_recent_requests(self, limit: int = 10) -> list[dict]:
		"""Get recent completed requests for agent analysis."""
		recent = self._completed_requests[-limit:] if self._completed_requests else []
		return [req.to_dict() for req in recent]

	def get_active_requests(self) -> list[dict]:
		"""Get currently active requests."""
		return [req.to_dict() for req in self._active_requests.values()]

	def get_api_requests(self, limit: int = 10) -> list[dict]:
		"""Get recent API requests (XHR/Fetch)."""
		api_requests = [req for req in self._completed_requests if req.is_api_call]
		return [req.to_dict() for req in api_requests[-limit:]]

	def get_ui_requests(self, limit: int = 10) -> list[dict]:
		"""Get recent UI resource requests (HTML, CSS, JS, images)."""
		ui_requests = [req for req in self._completed_requests if req.is_ui_resource]
		return [req.to_dict() for req in ui_requests[-limit:]]

	def get_failed_requests(self, limit: int = 10) -> list[dict]:
		"""Get recent failed requests."""
		failed = [req for req in self._completed_requests if req.failed]
		return [req.to_dict() for req in failed[-limit:]]

	def get_requests_by_status(self, status_code: int, limit: int = 10) -> list[dict]:
		"""Get requests by HTTP status code."""
		filtered = [req for req in self._completed_requests if req.response_status == status_code]
		return [req.to_dict() for req in filtered[-limit:]]

	def get_requests_summary(self) -> dict:
		"""Get summary statistics of network activity."""
		total_requests = len(self._completed_requests)
		api_requests = len([req for req in self._completed_requests if req.is_api_call])
		failed_requests = len([req for req in self._completed_requests if req.failed])
		active_requests = len(self._active_requests)

		return {
			'total_completed': total_requests,
			'api_requests': api_requests,
			'failed_requests': failed_requests,
			'active_requests': active_requests,
			'success_rate': ((total_requests - failed_requests) / total_requests * 100) if total_requests > 0 else 0,
		}

	def get_requests_by_trigger(self, trigger_pattern: str, limit: int = 10) -> list[dict]:
		"""Get requests filtered by likely UI trigger pattern."""
		filtered = []
		for req in self._completed_requests:
			trigger = req.likely_ui_trigger
			if trigger and trigger_pattern.lower() in trigger.lower():
				filtered.append(req)
		return [req.to_dict() for req in filtered[-limit:]]

	def get_user_triggered_requests(self, limit: int = 10) -> list[dict]:
		"""Get requests that appear to be triggered by user interactions."""
		user_patterns = ['click', 'submit', 'change', 'input', 'form submission', 'search', 'filter']
		filtered = []
		for req in self._completed_requests:
			trigger = req.likely_ui_trigger
			if trigger and any(pattern in trigger.lower() for pattern in user_patterns):
				filtered.append(req)
		return [req.to_dict() for req in filtered[-limit:]]

	def analyze_recent_user_action(self, seconds_back: int = 30) -> dict:
		"""Analyze recent network activity that might correlate with user actions."""
		import time
		cutoff_time = time.time() - seconds_back

		recent_requests = [
			req for req in self._completed_requests
			if req.start_time >= cutoff_time
		]

		user_triggered = [
			req for req in recent_requests
			if req.likely_ui_trigger and any(
				pattern in req.likely_ui_trigger.lower()
				for pattern in ['click', 'submit', 'change', 'input', 'form']
			)
		]

		api_calls = [req for req in recent_requests if req.is_api_call]
		failed_requests = [req for req in recent_requests if req.failed]

		return {
			'time_window_seconds': seconds_back,
			'total_requests': len(recent_requests),
			'user_triggered_requests': len(user_triggered),
			'api_calls': len(api_calls),
			'failed_requests': len(failed_requests),
			'recent_user_actions': [
				{
					'url': req.url,
					'trigger': req.likely_ui_trigger,
					'status': req.response_status,
					'duration': req.duration
				}
				for req in user_triggered[-5:]  # Last 5 user actions
			],
			'recent_api_calls': [
				{
					'url': req.url,
					'method': req.method,
					'status': req.response_status,
					'trigger': req.likely_ui_trigger
				}
				for req in api_calls[-5:]  # Last 5 API calls
			]
		}

	async def _analyze_dom_correlation(self, tracker: NetworkRequestTracker) -> None:
		"""Analyze DOM context to correlate the request with UI elements."""
		try:
			# Get current DOM snapshot from the DOM watchdog if available
			dom_watchdog = getattr(self.browser_session, '_dom_watchdog', None)
			if not dom_watchdog:
				# Fallback: analyze based on URL patterns and initiator
				tracker.analyze_dom_context(None)
				return

			# Try to get cached DOM state or request fresh one
			try:
				# Get viewport info for position analysis
				viewport_info = getattr(self.browser_session.browser_profile, 'viewport', None)
				if viewport_info:
					tracker.identify_ui_section_by_position(
						viewport_width=viewport_info.get('width', 1280),
						viewport_height=viewport_info.get('height', 720)
					)
			except Exception:
				pass

			# Analyze based on available information
			tracker.analyze_dom_context(None)

		except Exception as e:
			self.logger.debug(f'[NetworkWatchdog] DOM correlation failed: {e}')
			# Fallback to basic analysis
			tracker.analyze_dom_context(None)

	def get_requests_by_ui_section(self, section_pattern: str, limit: int = 10) -> list[dict]:
		"""Get requests filtered by UI section."""
		filtered = []
		for req in self._completed_requests:
			if req.ui_section and section_pattern.lower() in req.ui_section.lower():
				filtered.append(req)
		return [req.to_dict() for req in filtered[-limit:]]

	def get_ui_section_summary(self) -> dict:
		"""Get summary of requests by UI section."""
		section_counts = {}
		for req in self._completed_requests:
			section = req.ui_section or "Unknown"
			section_counts[section] = section_counts.get(section, 0) + 1

		return {
			'total_sections': len(section_counts),
			'section_breakdown': section_counts,
			'most_active_section': max(section_counts.items(), key=lambda x: x[1]) if section_counts else None
		}

	def clear_request_history(self) -> None:
		"""Clear stored request history."""
		self._completed_requests.clear()
		self.logger.info('[NetworkWatchdog] Request history cleared')