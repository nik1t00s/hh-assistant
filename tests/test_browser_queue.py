import unittest
from unittest.mock import Mock

from browser_queue import BrowserQueue, suitable_urls


class Scheduler:
    def __init__(self):
        self.callbacks = {}
        self.delays = []
        self.counter = 0

    def after(self, delay, callback):
        self.counter += 1
        self.delays.append(delay)
        self.callbacks[self.counter] = callback
        return self.counter

    def after_cancel(self, token):
        self.callbacks.pop(token, None)

    def tick(self):
        token = next(iter(self.callbacks))
        self.callbacks.pop(token)()


class BrowserQueueTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = Scheduler()
        self.opener = Mock(return_value=True)
        self.queue = BrowserQueue(self.scheduler, Mock(), self.opener)

    def test_first_immediate_then_twenty_seconds_and_no_duplicate_start(self):
        self.queue.start(['https://example.com/1', 'https://example.com/2'])
        self.queue.start(['https://example.com/3'])
        self.opener.assert_called_once_with('https://example.com/1')
        self.assertEqual(self.scheduler.delays, [20000])
        self.scheduler.tick()
        self.assertEqual(self.opener.call_args.args, ('https://example.com/2',))
        self.assertFalse(self.queue.active)
        self.assertFalse(self.scheduler.callbacks)

    def test_cancel_invalidates_old_callback_and_allows_new_queue(self):
        self.queue.start(['https://example.com/1', 'https://example.com/2'])
        stale = next(iter(self.scheduler.callbacks.values()))
        self.queue.cancel()
        self.assertFalse(self.scheduler.callbacks)
        self.queue.start(['https://example.com/3'])
        stale()
        self.assertEqual(self.opener.call_count, 2)
        self.opener.assert_called_with('https://example.com/3')

    def test_browser_failure_stops_queue(self):
        for failure in (False, RuntimeError('unavailable')):
            with self.subTest(failure=failure):
                self.opener.side_effect = failure if isinstance(failure, Exception) else None
                self.opener.return_value = False
                self.queue.start(['https://example.com/1', 'https://example.com/2'])
                self.assertFalse(self.queue.active)
                self.assertFalse(self.scheduler.callbacks)

    def test_selection_uses_latest_verdict_and_only_web_links(self):
        def row(url, suitable=True, verdict='MATCH'):
            return dict(url=url, suitable=suitable, verdict=verdict)
        rows = [row('https://example.com/1'), row('https://example.com/2'),
                row('https://example.com/1', False, 'REJECT'),
                row('https://example.com/2'), row('https://example.com/3', True, 'WEAK'),
                row('file:///secret'), row('javascript:alert(1)'),
                row('https://example.com/4', None), row(None)]
        self.assertEqual(suitable_urls(rows), ['https://example.com/2', 'https://example.com/3'])


if __name__ == '__main__':
    unittest.main()
