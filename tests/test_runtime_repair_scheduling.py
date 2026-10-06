"""Private cloud requests must not enter local repair incident queues."""
import unittest
import main

class RuntimeRepairSchedulingTests(unittest.TestCase):
    def test_cloud_app_has_no_local_incident_writer(self):
        self.assertFalse(hasattr(main, '_schedule_autonomous_repair'))
        self.assertFalse(hasattr(main, 'enqueue_runtime_incident'))
        self.assertFalse(hasattr(main, 'record_quality_incident'))
