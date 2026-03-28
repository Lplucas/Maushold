import sys
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

# Add the project root to the Python path so that tests can import
# bot, api, and database modules from the root directory.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def mock_update():
    """
    Reusable mock for telegram.Update with pre-configured attributes.
    All bot command handlers receive (update, context) — this fixture
    provides a properly shaped Update mock with AsyncMock reply methods.
    """
    update = MagicMock()
    update.message.reply_text = AsyncMock()
    update.effective_user.id = 12345
    update.effective_user.first_name = "Lucas"
    update.effective_user.username = "lucas_test"
    return update


@pytest.fixture
def mock_context():
    """
    Reusable mock for telegram.ext.ContextTypes.DEFAULT_TYPE.
    Set context.args in individual tests to simulate command arguments.
    """
    context = MagicMock()
    context.args = []
    return context
