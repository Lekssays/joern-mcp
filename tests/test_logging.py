"""
Tests for logging configuration
"""
import logging
import sys
from unittest.mock import patch, MagicMock
from src.utils.logging import setup_logging, get_logger


class TestSetupLogging:
    """Test logging setup functionality"""

    def test_setup_logging_default_level(self):
        """Test setting up logging with default INFO level"""
        with patch('logging.getLogger') as mock_get_logger, \
             patch('sys.stdout', create=True) as mock_stdout:

            mock_root_logger = MagicMock()
            mock_docker_logger = MagicMock()
            mock_urllib_logger = MagicMock()
            mock_git_logger = MagicMock()

            def get_logger_side_effect(name=None):
                if name == 'docker':
                    return mock_docker_logger
                elif name == 'urllib3':
                    return mock_urllib_logger
                elif name == 'git':
                    return mock_git_logger
                else:
                    return mock_root_logger

            mock_get_logger.side_effect = get_logger_side_effect

            setup_logging()

            # Verify root logger configuration
            mock_root_logger.setLevel.assert_called_once_with(logging.INFO)
            assert mock_root_logger.addHandler.called

            # Verify handler was added
            handler_call = mock_root_logger.addHandler.call_args[0][0]
            assert isinstance(handler_call, logging.StreamHandler)
            assert handler_call.level == logging.INFO

            # Verify library loggers are set to WARNING
            mock_docker_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_urllib_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_git_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_setup_logging_custom_level(self):
        """Test setting up logging with custom log level"""
        with patch('logging.getLogger') as mock_get_logger, \
             patch('sys.stdout', create=True) as mock_stdout:

            mock_root_logger = MagicMock()
            mock_docker_logger = MagicMock()
            mock_urllib_logger = MagicMock()
            mock_git_logger = MagicMock()

            def get_logger_side_effect(name=None):
                if name == 'docker':
                    return mock_docker_logger
                elif name == 'urllib3':
                    return mock_urllib_logger
                elif name == 'git':
                    return mock_git_logger
                else:
                    return mock_root_logger

            mock_get_logger.side_effect = get_logger_side_effect

            setup_logging("DEBUG")

            # Verify root logger configuration
            mock_root_logger.setLevel.assert_called_once_with(logging.DEBUG)

    def test_setup_logging_invalid_level(self):
        """Test setting up logging with invalid level defaults to INFO"""
        with patch('logging.getLogger') as mock_get_logger, \
             patch('sys.stdout', create=True) as mock_stdout:

            mock_root_logger = MagicMock()
            mock_docker_logger = MagicMock()
            mock_urllib_logger = MagicMock()
            mock_git_logger = MagicMock()

            def get_logger_side_effect(name=None):
                if name == 'docker':
                    return mock_docker_logger
                elif name == 'urllib3':
                    return mock_urllib_logger
                elif name == 'git':
                    return mock_git_logger
                else:
                    return mock_root_logger

            mock_get_logger.side_effect = get_logger_side_effect

            setup_logging("INVALID")

            # Should default to INFO for invalid level
            mock_root_logger.setLevel.assert_called_once_with(logging.INFO)

    def test_setup_logging_removes_existing_handlers(self):
        """Test that existing handlers are removed before setup"""
        with patch('logging.getLogger') as mock_get_logger, \
             patch('sys.stdout', create=True) as mock_stdout:

            mock_root_logger = MagicMock()
            mock_root_logger.handlers = [MagicMock(), MagicMock()]  # Existing handlers
            mock_get_logger.return_value = mock_root_logger

            setup_logging()

            # Verify existing handlers were removed
            assert mock_root_logger.removeHandler.call_count == 2

    def test_setup_logging_library_noise_reduction(self):
        """Test that noisy library loggers are configured"""
        with patch('logging.getLogger') as mock_get_logger, \
             patch('sys.stdout', create=True) as mock_stdout:

            mock_root_logger = MagicMock()
            mock_docker_logger = MagicMock()
            mock_urllib_logger = MagicMock()
            mock_git_logger = MagicMock()

            def get_logger_side_effect(name=None):
                if name == 'docker':
                    return mock_docker_logger
                elif name == 'urllib3':
                    return mock_urllib_logger
                elif name == 'git':
                    return mock_git_logger
                else:
                    return mock_root_logger

            mock_get_logger.side_effect = get_logger_side_effect

            setup_logging()

            # Verify library loggers are set to WARNING
            mock_docker_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_urllib_logger.setLevel.assert_called_once_with(logging.WARNING)
            mock_git_logger.setLevel.assert_called_once_with(logging.WARNING)

    def test_setup_logging_formatter(self):
        """Test that handlers get proper formatter"""
        with patch('logging.getLogger') as mock_get_logger, \
             patch('sys.stdout', create=True) as mock_stdout:

            mock_root_logger = MagicMock()
            mock_get_logger.return_value = mock_root_logger

            setup_logging()

            # Get the handler that was added
            handler = mock_root_logger.addHandler.call_args[0][0]

            # Verify formatter was set
            assert handler.formatter is not None
            assert isinstance(handler.formatter, logging.Formatter)

            # Test the format string
            format_str = handler.formatter._fmt
            expected_parts = [
                '%(asctime)s',
                '%(name)s',
                '%(levelname)s',
                '%(message)s'
            ]

            for part in expected_parts:
                assert part in format_str


class TestGetLogger:
    """Test logger retrieval"""

    def test_get_logger(self):
        """Test getting a logger instance"""
        with patch('logging.getLogger') as mock_get_logger:
            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            logger = get_logger("test.module")

            mock_get_logger.assert_called_once_with("test.module")
            assert logger == mock_logger

    def test_get_logger_different_names(self):
        """Test getting loggers with different names"""
        with patch('logging.getLogger') as mock_get_logger:
            mock_logger1 = MagicMock()
            mock_logger2 = MagicMock()
            mock_get_logger.side_effect = [mock_logger1, mock_logger2]

            logger1 = get_logger("module1")
            logger2 = get_logger("module2")

            assert mock_get_logger.call_count == 2
            mock_get_logger.assert_any_call("module1")
            mock_get_logger.assert_any_call("module2")
            assert logger1 == mock_logger1
            assert logger2 == mock_logger2