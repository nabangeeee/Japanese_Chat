import unittest
from unittest.mock import Mock, patch
from automation.auto_repair import deployment_ready, rollback

class RepairDeploymentTests(unittest.TestCase):
    def test_old_revision_does_not_count_as_deployed(self):
        response=Mock(status_code=200)
        response.json.return_value={'enabled':True,'revision':'old'}
        with patch('automation.auto_repair.httpx.Client') as factory, patch('automation.auto_repair.time.sleep'):
            factory.return_value.__enter__.return_value.get.return_value=response
            self.assertFalse(deployment_ready('new',attempts=1))

    def test_exact_revision_requires_anonymous_denial(self):
        status=Mock(status_code=200)
        status.json.return_value={'enabled':True,'revision':'new'}
        with patch('automation.auto_repair.httpx.Client') as factory, patch('automation.auto_repair.time.sleep'):
            factory.return_value.__enter__.return_value.get.side_effect=[status,Mock(status_code=200),Mock(status_code=401)]
            self.assertTrue(deployment_ready('new',attempts=1))

    def test_concurrent_local_change_prevents_rollback(self):
        with patch('automation.auto_repair.improvement._git_push_target',return_value=('main','main','remote')), patch('automation.auto_repair.improvement._git_head',return_value='other'), patch('automation.auto_repair.subprocess.run') as run:
            self.assertIsNone(rollback('candidate'))
        run.assert_not_called()
