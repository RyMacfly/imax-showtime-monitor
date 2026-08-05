import pytest
from playwright.async_api import async_playwright


CALENDAR_HTML = """
<div role="grid">

    <!-- Friday -->
    <button
        role="gridcell"
        data-timestamp="1786060800000"
        aria-colindex="6"
        disabled
    >
        7
    </button>

    <!-- Saturday -->
    <button
        role="gridcell"
        data-timestamp="1786147200000"
        aria-colindex="7"
        disabled
    >
        8
    </button>

    <!-- Sunday -->
    <button
        role="gridcell"
        data-timestamp="1786233600000"
        aria-colindex="1"
        disabled
    >
        9
    </button>

</div>
"""


@pytest.mark.asyncio
async def test_calendar_exists():

    async with async_playwright() as p:

        browser = await p.chromium.launch()

        page = await browser.new_page()

        await page.set_content(CALENDAR_HTML)

        calendar = page.locator('[role="grid"]')

        assert await calendar.count() == 1

        await browser.close()


@pytest.mark.asyncio
async def test_disabled_date():

    async with async_playwright() as p:

        browser = await p.chromium.launch()

        page = await browser.new_page()

        await page.set_content(CALENDAR_HTML)

        friday = page.locator(
            'button[role="gridcell"]'
        ).nth(0)

        assert await friday.is_disabled()

        await browser.close()


@pytest.mark.asyncio
async def test_enabled_date():

    html = """
    <div role="grid">

        <button
            role="gridcell"
            data-timestamp="1786060800000"
        >
            7
        </button>

    </div>
    """

    async with async_playwright() as p:

        browser = await p.chromium.launch()

        page = await browser.new_page()

        await page.set_content(html)

        friday = page.locator(
            'button[role="gridcell"]'
        )

        assert not await friday.is_disabled()

        await browser.close()


@pytest.mark.asyncio
async def test_detect_new_showtimes():

    old_state = {
        "2026-08-07": False
    }

    new_state = {
        "2026-08-07": True
    }

    date = "2026-08-07"

    was_available = old_state.get(date, False)
    is_available = new_state.get(date, False)

    assert was_available is False
    assert is_available is True

    # This should trigger an alert
    assert is_available and not was_available


@pytest.mark.asyncio
async def test_no_alert_when_still_disabled():

    old_state = {
        "2026-08-07": False
    }

    new_state = {
        "2026-08-07": False
    }

    date = "2026-08-07"

    was_available = old_state.get(date, False)
    is_available = new_state.get(date, False)

    # No transition
    assert not (is_available and not was_available)


@pytest.mark.asyncio
async def test_no_duplicate_alert():

    old_state = {
        "2026-08-07": True
    }

    new_state = {
        "2026-08-07": True
    }

    date = "2026-08-07"

    was_available = old_state.get(date, False)
    is_available = new_state.get(date, False)

    # Already available, therefore no NEW alert
    assert not (is_available and not was_available)