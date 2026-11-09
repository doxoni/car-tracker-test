# -*- coding: utf-8 -*-
"""Скриншоты Mini App с подставленными данными (для проверки дизайна).

Запуск (PowerShell, из папки проекта):
    python tools/shoot_ui.py

Скриншоты кладутся в .shots/ (папка в .gitignore).
"""

import asyncio
import os

from playwright.async_api import async_playwright

BASE = os.getenv("UI_BASE_URL", "http://127.0.0.1:5055")
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".shots")

VEHICLES = [
    {"id": 1, "brand": "MAN", "plate": "АА111АА", "status": "active",
     "current_mileage": 245000, "avg_fuel_consumption": 34.5},
    {"id": 2, "brand": "Volvo", "plate": "ВВ222ВВ", "status": "active",
     "current_mileage": 131500, "avg_fuel_consumption": 31.0},
]

EXPENSES = [
    {"id": 1, "vehicle_id": 1, "category": "топливо", "amount": 8500,
     "date": "2026-11-08", "comment": "Заправка", "status": "approved"},
    {"id": 2, "vehicle_id": 2, "category": "ремонт", "amount": 12300,
     "date": "2026-11-07", "comment": "ТО", "status": "pending"},
    {"id": 3, "vehicle_id": 1, "category": "мойка", "amount": 700,
     "date": "2026-11-06", "comment": "", "status": "approved"},
]

BARRELS = [
    {"id": 1, "name": "Дизель", "fuel_type": "diesel", "current": 1200,
     "capacity": 2000, "threshold_liters": 300, "remaining_pct": 60.0,
     "is_low": False, "formatted_current": "1 200 л",
     "formatted_remaining": "1 200 л"},
]

ROUTES = {
    "/api/auth/verify": {"ok": True, "user": {"id": 1, "tg_id": 1, "username": "Koval",
                                               "level": 3, "role": "суперадмин", "is_admin": True}},
    "/api/dashboard": {"period": "month", "total_amount": 21500,
                       "by_category": [{"category": "топливо", "total": 8500},
                                       {"category": "ремонт", "total": 12300}],
                       "top_vehicles": [{"brand": "MAN", "plate": "АА111АА", "total": 8500},
                                         {"brand": "Volvo", "plate": "ВВ222ВВ", "total": 12300}],
                       "barrels": BARRELS},
    "/api/vehicles": VEHICLES,
    "/api/expenses": EXPENSES,
    "/api/barrels": BARRELS,
    "/api/reports": {"reports": []},
}

TABS = ["dashboard", "vehicles", "expenses", "barrels", "reports"]


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 400, "height": 860})

        # Подставляем ответы API: страница рисуется как с живой базой.
        async def handle(route):
            url = route.request.url.split("?")[0]
            path = url.replace(BASE, "")
            body = ROUTES.get(path)
            if body is None:
                await route.fulfill(status=404, content_type="application/json",
                                    body='{"error":"not found"}')
            else:
                import json
                await route.fulfill(status=200, content_type="application/json",
                                    body=json.dumps(body, ensure_ascii=False))

        await page.route("**/api/**", handle)

        # initData передаём через query: настоящий telegram-web-app.js
        # перетирает объект Telegram, и подставленный initData пропадает.
        await page.goto(
            f"{BASE}/app?initData=user%3D%7B%22id%22%3A1%7D",
            wait_until="networkidle",
        )
        await page.wait_for_timeout(800)

        for tab in TABS:
            await page.evaluate("name => showTab(name)", tab)
            await page.wait_for_timeout(700)
            await page.screenshot(path=f"{OUT}/ui_{tab}.png", full_page=True)
            print(f"снято: ui_{tab}.png")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
