import asyncio
import os
import unittest
from unittest.mock import patch
from fastapi import BackgroundTasks, HTTPException
import main


class ApplicationProviderTests(unittest.TestCase):
    def test_citation_urls_survive_japanese_cleanup(self):
        text = '東京です。 [出典 1](https://example.com/a?q=1)'
        self.assertEqual(main.clean_japanese_text(text), text)

    def test_provider_failures_do_not_trigger_repair_or_success_payloads(self):
        import httpx
        from openai import APIStatusError, APIConnectionError
        request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
        for route, req in [(main.chat, main.ChatRequest(message='こんにちは', api_key='key')), (main.multi_chat, main.ChatRequest(message='こんにちは', api_key='key')), (main.translate, main.TranslateRequest(text='こんにちは', api_key='key')), (main.furigana, main.TranslateRequest(text='学校', api_key='key'))]:
            for status in [401, 403, 429, 503]:
                error = APIStatusError('SECRET_PROVIDER_BODY', response=httpx.Response(status, request=request), body=None)
                with self.subTest(route=route.__name__, status=status), patch('main.generate_text', side_effect=error) as generate, patch('main.get_system_prompt', return_value='system'), patch('main._schedule_autonomous_repair') as repair:
                    with self.assertRaises(HTTPException) as raised:
                        asyncio.run(route(req, BackgroundTasks()))
                    self.assertEqual(raised.exception.status_code, status)
                    self.assertNotIn('SECRET_PROVIDER_BODY', str(raised.exception.detail))
                    generate.assert_called_once()
                    repair.assert_not_called()

    def test_all_foreground_routes_and_feedback_use_openai(self):
        self.assertTrue(hasattr(main, 'generate_text'), 'routes still use old provider')
        with patch.dict(os.environ, {'OPENAI_API_KEY':'server-key'}), patch('main.generate_text') as generate, patch('main.get_system_prompt', return_value='system'), patch('main.save_message_feedback', return_value={}), patch('main._schedule_autonomous_repair') as repair:
            generate.return_value = 'こんにちは。'
            tasks = BackgroundTasks()
            result = asyncio.run(main.chat(main.ChatRequest(message='news', api_key=''), tasks))
            self.assertEqual(result['response'], 'こんにちは。')
            self.assertEqual(generate.call_args.args[0], 'server-key')
            self.assertTrue(generate.call_args.kwargs['web_search'])
            self.assertEqual(len(tasks.tasks), 1)
            result = asyncio.run(main.multi_chat(main.ChatRequest(message='こんにちは', api_key=''), BackgroundTasks()))
            self.assertEqual(len(result['responses']), 2)
            generate.return_value = '안녕하세요.'
            self.assertEqual(asyncio.run(main.translate(main.TranslateRequest(text='こんにちは', api_key=''), BackgroundTasks()))['translation'], '안녕하세요.')
            generate.return_value = '学校(がっこう)'
            self.assertEqual(asyncio.run(main.furigana(main.TranslateRequest(text='学校', api_key=''), BackgroundTasks()))['furigana'], '学校(がっこう)')
            tasks = BackgroundTasks()
            asyncio.run(main.api_submit_feedback(main.FeedbackRequest(message_id='ast_1', rating=-1, feedback_text='더 짧게'), tasks))
            self.assertEqual(tasks.tasks[0].args[0], 'server-key')
            repair.assert_not_called()

    def test_learning_background_parsers(self):
        self.assertTrue(hasattr(main, 'generate_text'), 'background tasks still use old provider')
        with patch('main.generate_text') as generate, patch('main.get_session_messages', return_value=[{'role':'user','content':'こんにちは'}]*6), patch('main.save_session_summary') as summary, patch('main.save_user_fact') as fact, patch('main.save_user_memory') as memory:
            generate.return_value = 'SUMMARY: 인사\nFACTS: hobby=reading'
            main._update_session_summary_background('key', 'sess')
            summary.assert_called_once_with('sess', '인사')
            fact.assert_called_once_with('hobby', 'reading')
            generate.return_value = 'ORIGINAL: 学校を行く\nCORRECTED: 学校へ行く\nEXPLANATION: 조사'
            main._extract_grammar_errors_background('key', '学校を行く', '学校へ行く')
            memory.assert_called_once()
            generate.return_value = 'RULE: 짧게 답하기'
            main._analyze_feedback_background('key', 'ast', None, -1, '짧게')
            self.assertEqual(fact.call_args.args[1], '짧게 답하기')
