"""E2E: настоящий браузер против live-сервера.

Шаблон для новых сценариев: e2e-tester сначала проходит сценарий через
Playwright MCP, затем фиксирует его здесь.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def test_home_page_in_browser(page: Page, live_server):
    page.goto(live_server.url)
    expect(page.get_by_role("heading", level=1)).to_contain_text("peer-review")
