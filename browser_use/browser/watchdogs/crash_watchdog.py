"""Browser watchdog for monitoring crashes using CDP."""

import asyncio
from typing import TYPE_CHECKING, ClassVar

import psutil
from bubus import BaseEvent
from cdp_use.cdp.target import SessionID, TargetID
from cdp_use.cdp.target.events import TargetCrashedEvent
from pydantic import Field, PrivateAttr

from browser_use.browser.events import (
	BrowserConnectedEvent,
	BrowserErrorEvent,
	BrowserStoppedEvent,
	TabCreatedEvent,
)
from browser_use.browser.watchdog_base import BaseWatchdog

if TYPE_CHECKING:
	pass



class CrashWatchdog(BaseWatchdog):
	"""Monitors browser health for crashes using CDP."""

	# Event contracts
	LISTENS_TO: ClassVar[list[type[BaseEvent]]] = [
		BrowserConnectedEvent,
		BrowserStoppedEvent,
		TabCreatedEvent,
	]
	EMITS: ClassVar[list[type[BaseEvent]]] = [BrowserErrorEvent]

	# Configuration
	check_interval_seconds: float = Field(default=5.0)  # Reduced frequency to reduce noise

	# Private state
	_monitoring_task: asyncio.Task | None = PrivateAttr(default=None)
	_last_responsive_checks: dict[str, float] = PrivateAttr(default_factory=dict)  # target_url -> timestamp
	_cdp_event_tasks: set[asyncio.Task] = PrivateAttr(default_factory=set)  # Track CDP event handler tasks
	_sessions_with_listeners: set[str] = PrivateAttr(default_factory=set)  # Track sessions that already have event listeners

	async def on_BrowserConnectedEvent(self, event: BrowserConnectedEvent) -> None:
		"""Start monitoring when browser is connected."""
		# logger.debug('[CrashWatchdog] Browser connected event received, beginning monitoring')

		asyncio.create_task(self._start_monitoring())
		# logger.debug(f'[CrashWatchdog] Monitoring task started: {self._monitoring_task and not self._monitoring_task.done()}')

	async def on_BrowserStoppedEvent(self, event: BrowserStoppedEvent) -> None:
		"""Stop monitoring when browser stops."""
		# logger.debug('[CrashWatchdog] Browser stopped, ending monitoring')
		await self._stop_monitoring()

	async def on_TabCreatedEvent(self, event: TabCreatedEvent) -> None:
		"""Attach to new tab."""
		assert self.browser_session.agent_focus is not None, 'No current target ID'
		await self.attach_to_target(self.browser_session.agent_focus.target_id)

	async def attach_to_target(self, target_id: TargetID) -> None:
		"""Set up crash monitoring for a specific target using CDP."""
		try:
			# Create temporary session for monitoring without switching focus
			cdp_session = await self.browser_session.get_or_create_cdp_session(target_id, focus=False)

			# Check if we already have listeners for this session
			if cdp_session.session_id in self._sessions_with_listeners:
				self.logger.debug(f'[CrashWatchdog] Event listeners already exist for session: {cdp_session.session_id}')
				return

			def on_target_crashed(event: TargetCrashedEvent, session_id: SessionID | None = None):
				# Create and track the task
				task = asyncio.create_task(self._on_target_crash_cdp(target_id))
				self._cdp_event_tasks.add(task)
				# Remove from set when done
				task.add_done_callback(lambda t: self._cdp_event_tasks.discard(t))

			cdp_session.cdp_client.register.Target.targetCrashed(on_target_crashed)

			# Track that we've added listeners to this session
			self._sessions_with_listeners.add(cdp_session.session_id)

			# Get target info for logging
			targets = await cdp_session.cdp_client.send.Target.getTargets()
			target_info = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)
			if target_info:
				self.logger.debug(f'[CrashWatchdog] Added target to monitoring: {target_info.get("url", "unknown")}')

		except Exception as e:
			self.logger.warning(f'[CrashWatchdog] Failed to attach to target {target_id}: {e}')


	async def _on_target_crash_cdp(self, target_id: TargetID) -> None:
		"""Handle target crash detected via CDP."""
		# Remove crashed session from pool
		if session := self.browser_session._cdp_session_pool.pop(target_id, None):
			await session.disconnect()
			self.logger.debug(f'[CrashWatchdog] Removed crashed session from pool: {target_id}')

		# Get target info
		cdp_client = self.browser_session.cdp_client
		targets = await cdp_client.send.Target.getTargets()
		target_info = next((t for t in targets['targetInfos'] if t['targetId'] == target_id), None)
		if (
			target_info
			and self.browser_session.agent_focus
			and target_info['targetId'] == self.browser_session.agent_focus.target_id
		):
			self.browser_session.agent_focus.target_id = None  # type: ignore
			self.browser_session.agent_focus.session_id = None  # type: ignore
			self.logger.error(
				f'[CrashWatchdog] 💥 Target crashed, navigating Agent to a new tab: {target_info.get("url", "unknown")}'
			)

		# Also emit generic browser error
		self.event_bus.dispatch(
			BrowserErrorEvent(
				error_type='TargetCrash',
				message=f'Target crashed: {target_id}',
				details={
					# 'url': target_url,  # TODO: add url to details
					'target_id': target_id,
				},
			)
		)

	async def _start_monitoring(self) -> None:
		"""Start the monitoring loop."""
		assert self.browser_session.cdp_client is not None, 'Root CDP client not initialized - browser may not be connected yet'

		if self._monitoring_task and not self._monitoring_task.done():
			# logger.info('[CrashWatchdog] Monitoring already running')
			return

		self._monitoring_task = asyncio.create_task(self._monitoring_loop())
		# logger.debug('[CrashWatchdog] Monitoring loop created and started')

	async def _stop_monitoring(self) -> None:
		"""Stop the monitoring loop."""
		if self._monitoring_task and not self._monitoring_task.done():
			self._monitoring_task.cancel()
			try:
				await self._monitoring_task
			except asyncio.CancelledError:
				pass
			self.logger.debug('[CrashWatchdog] Monitoring loop stopped')

		# Cancel all CDP event handler tasks
		for task in list(self._cdp_event_tasks):
			if not task.done():
				task.cancel()
		# Wait for all tasks to complete cancellation
		if self._cdp_event_tasks:
			await asyncio.gather(*self._cdp_event_tasks, return_exceptions=True)
		self._cdp_event_tasks.clear()

		# Clear tracking (CDP sessions are cached and managed by BrowserSession)
		self._sessions_with_listeners.clear()

	async def _monitoring_loop(self) -> None:
		"""Main monitoring loop."""
		await asyncio.sleep(10)  # give browser time to start up and load the first page after first LLM call
		while True:
			try:
				await self._check_browser_health()
				await asyncio.sleep(self.check_interval_seconds)
			except asyncio.CancelledError:
				break
			except Exception as e:
				self.logger.error(f'[CrashWatchdog] Error in monitoring loop: {e}')

	async def _check_browser_health(self) -> None:
		"""Check if browser and targets are still responsive."""

		try:
			try:
				self.logger.debug(f'[CrashWatchdog] Checking browser health for target {self.browser_session.agent_focus}')
				cdp_session = await self.browser_session.get_or_create_cdp_session()
			except Exception as e:
				self.logger.debug(
					f'[CrashWatchdog] Checking browser health for target {self.browser_session.agent_focus} error: {type(e).__name__}: {e}'
				)
				self.agent_focus = cdp_session = await self.browser_session.get_or_create_cdp_session(
					target_id=self.agent_focus.target_id, new_socket=True, focus=True
				)

			for target in (await self.browser_session.cdp_client.send.Target.getTargets()).get('targetInfos', []):
				if target.get('type') == 'page':
					cdp_session = await self.browser_session.get_or_create_cdp_session(target_id=target.get('targetId'))
					if self._is_new_tab_page(target.get('url')) and target.get('url') != 'about:blank':
						self.logger.debug(
							f'[CrashWatchdog] Redirecting chrome://new-tab-page/ to about:blank {target.get("url")}'
						)
						await cdp_session.cdp_client.send.Page.navigate(
							params={'url': 'about:blank'}, session_id=cdp_session.session_id
						)

			# Quick ping to check if session is alive
			self.logger.debug(f'[CrashWatchdog] Attempting to run simple JS test expression in session {cdp_session} 1+1')
			await asyncio.wait_for(
				cdp_session.cdp_client.send.Runtime.evaluate(params={'expression': '1+1'}, session_id=cdp_session.session_id),
				timeout=1.0,
			)
			self.logger.debug(f'[CrashWatchdog] Browser health check passed for target {self.browser_session.agent_focus}')
		except Exception as e:
			self.logger.error(
				f'[CrashWatchdog] ❌ Crashed session detected for target {self.browser_session.agent_focus} error: {type(e).__name__}: {e}'
			)
			# Remove crashed session from pool
			if self.browser_session.agent_focus and (target_id := self.browser_session.agent_focus.target_id):
				if session := self.browser_session._cdp_session_pool.pop(target_id, None):
					await session.disconnect()
					self.logger.debug(f'[CrashWatchdog] Removed crashed session from pool: {target_id}')
			self.browser_session.agent_focus.target_id = None  # type: ignore

		# Check browser process if we have PID
		if self.browser_session._local_browser_watchdog and (proc := self.browser_session._local_browser_watchdog._subprocess):
			try:
				if proc.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
					self.logger.error(f'[CrashWatchdog] Browser process {proc.pid} has crashed')
					# Clear all sessions from pool when browser crashes
					for session in self.browser_session._cdp_session_pool.values():
						await session.disconnect()
					self.browser_session._cdp_session_pool.clear()
					self.logger.debug('[CrashWatchdog] Cleared all sessions from pool due to browser crash')

					self.event_bus.dispatch(
						BrowserErrorEvent(
							error_type='BrowserProcessCrashed',
							message=f'Browser process {proc.pid} has crashed',
							details={'pid': proc.pid, 'status': proc.status()},
						)
					)
					await self._stop_monitoring()
					return
			except Exception:
				pass  # psutil not available or process doesn't exist

	@staticmethod
	def _is_new_tab_page(url: str) -> bool:
		"""Check if URL is a new tab page."""
		return url in ['about:blank', 'chrome://new-tab-page/', 'chrome://newtab/']
