def test_info_toast_lives_8s(server, page):
    page.clock.install()
    page.goto(server.url)
    page.evaluate("MH.notify('Сохранено')")
    page.clock.run_for(7500)
    assert page.locator(".toast").count() == 1
    page.clock.run_for(1000)
    assert page.locator(".toast").count() == 0


def test_hover_pauses_dismissal(server, page):
    page.clock.install()
    page.goto(server.url)
    page.evaluate("MH.notify('Сохранено')")
    page.locator(".toast").hover()
    page.clock.run_for(20000)
    assert page.locator(".toast").count() == 1


def test_error_is_assertive_and_sticky(server, page):
    page.clock.install()
    page.goto(server.url)
    page.evaluate("MH.notify('Сбой', {kind:'error'})")
    page.clock.run_for(60000)
    assert page.locator(".toast").count() == 1
    assert "Сбой" in page.locator("#mh-live-assertive").inner_text()


def test_info_goes_to_polite_region(server, page):
    page.goto(server.url)
    page.evaluate("MH.notify('Готово к работе')")
    assert "Готово к работе" in page.locator("#mh-live-polite").inner_text()


def test_log_keeps_last_50(server, page):
    page.goto(server.url)
    page.evaluate("for(let i=0;i<60;i++)MH.notify('m'+i)")
    assert page.evaluate("MH.getLog().length") == 50
    assert page.evaluate("MH.getLog()[0].text") == "m10"
    assert page.locator(".toast").count() <= 3


def test_escape_dismisses_toast_and_bell_opens_log_with_action(server, page):
    page.goto(server.url)
    page.evaluate("MH.notify('Готово',{action:{label:'Загрузки',fn:()=>location.hash='#downloads'}})")
    page.keyboard.press("Escape")
    assert page.locator(".toast").count() == 0
    page.locator("#bellBtn").click()
    page.locator("#logDlg").get_by_role("button", name="Загрузки").click()
    assert page.url.endswith("#downloads")


def test_toast_text_is_not_html(server, page):
    page.goto(server.url)
    page.evaluate("MH.notify('<b>жирный</b>')")
    assert page.locator(".toast b").count() == 0
    assert "<b>жирный</b>" in page.locator(".toast").inner_text()


def test_connection_lost_and_restored(server, page):
    page.goto(server.url)
    page.route("**/api/jobs", lambda r: r.abort())
    page.wait_for_timeout(2500)
    assert "Связь с MediaHub потеряна" in page.locator("#mh-live-assertive").inner_text()
    page.unroute("**/api/jobs")
    page.wait_for_timeout(6500)
    assert "Связь восстановлена" in page.locator("#mh-live-polite").inner_text()
    assert page.locator(".toast", has_text="потеряна").count() == 0
