import json


def _ann(page, prev, nxt):
    return page.evaluate("([a,b])=>import('/js/views/downloads.js').then(m=>m.jobAnnouncements(a,b))", [prev, nxt])


def j(**k):
    return {"id": 1, "title": "Видео", "kind": "video", "status": "качается", "pct": 0, **k}


def test_milestones_start_finish_error(server, page):
    page.goto(server.url)
    assert _ann(page, [], [j()]) == ["Видео: началась загрузка"]
    assert _ann(page, [j(pct=20)], [j(pct=30)]) == ["Видео: 25 %"]
    assert _ann(page, [j(pct=30)], [j(pct=40)]) == []
    assert _ann(page, [j(pct=90)], [j(pct=100, status="готово")]) == ["Видео: готово"]
    assert _ann(page, [j(pct=10)], [j(status="ошибка: сеть")]) == ["Видео: ошибка: сеть"]


def test_queue_and_planned_statuses(server, page):
    page.goto(server.url)
    assert _ann(page, [], [j(status="в очереди")]) == ["Видео: в очереди"]
    assert _ann(page, [j(status="в очереди")], [j(status="качается")]) == ["Видео: началась загрузка"]
    assert _ann(page, [], [j(status="запл. на 10:00")]) == []
    assert _ann(page, [j(status="готово")], [j(status="готово")]) == []


def test_bottom_bar_is_link_without_status_role(server, page):
    page.goto(server.url)
    page.evaluate("import('/js/views/downloads.js').then(m=>m.drawBar([{id:1,title:'v',status:'качается',pct:10,speed:0}]))")
    bar = page.locator("#bar")
    page.wait_for_selector("#bar:not(.hide)")
    assert bar.get_attribute("role") is None
    assert bar.locator("a[href='#downloads']").count() == 1
    bar.locator("a").click()
    assert page.url.endswith("#downloads")


def test_job_progressbar_has_role_and_value(server, page):
    page.goto(server.url + "/#downloads")
    page.evaluate("import('/js/views/downloads.js').then(m=>m.drawJobs([{id:1,title:'v',kind:'video',status:'качается',pct:42}]))")
    pb = page.get_by_role("progressbar")
    assert pb.get_attribute("aria-valuenow") == "42"
    assert "v" in pb.get_attribute("aria-label")


def test_cancel_button_named_and_delegated(server, page):
    sent = []
    page.route("**/api/cancel", lambda r: (sent.append(json.loads(r.request.post_data)), r.fulfill(status=200, content_type="application/json", body="{}")))
    page.goto(server.url + "/#downloads")
    page.evaluate("import('/js/views/downloads.js').then(m=>m.drawJobs([{id:7,title:'Фильм',kind:'video',status:'качается',pct:5}]))")
    page.get_by_role("button", name="Отменить: Фильм").click()
    page.wait_for_timeout(300)
    assert sent == [{"id": 7}]
    assert page.evaluate("document.querySelectorAll('#jobs [onclick]').length") == 0


def test_driver_announces_start_then_finish(server, page):
    state = {"n": 0}

    def jobs(route):
        state["n"] += 1
        body = [] if state["n"] <= 2 else [j(status="качается", pct=5)] if state["n"] <= 4 else [j(status="готово", pct=100)]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    page.route("**/api/jobs", jobs)
    page.goto(server.url)
    page.wait_for_function("document.getElementById('mh-live-polite').textContent.includes('началась загрузка')", timeout=8000)
    page.wait_for_function("document.getElementById('mh-live-polite').textContent.includes('готово')", timeout=8000)


def test_driver_error_is_assertive(server, page):
    state = {"n": 0}

    def jobs(route):
        state["n"] += 1
        body = [] if state["n"] <= 2 else [j(status="ошибка: нет места", pct=1)]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
    page.route("**/api/jobs", jobs)
    page.goto(server.url)
    page.wait_for_function("document.getElementById('mh-live-assertive').textContent.includes('нет места')", timeout=8000)


def test_first_poll_does_not_announce_old_jobs(server, page):
    page.route("**/api/jobs", lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps([j(status="готово", pct=100), j(id=2, status="качается", pct=50)])))
    page.goto(server.url)
    page.wait_for_timeout(2500)
    assert page.locator("#mh-live-polite").inner_text().strip() in ("", "\u00a0")
