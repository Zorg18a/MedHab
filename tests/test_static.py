import http.client


def test_js_served_as_javascript(server, page):
    r = page.request.get(server.url + "/js/main.js")
    assert r.status == 200 and r.headers["content-type"].startswith("text/javascript")


def test_css_content_type(server, page):
    assert page.request.get(server.url + "/css/tokens.css").headers["content-type"].startswith("text/css")


def test_traversal_and_other_extensions_rejected(server, page):
    for u in ("/js/../app.py", "/js/%2e%2e/app.py", "/js/x.py", "/js/"):
        assert page.request.get(server.url + u).status in (403, 404), u


def test_host_check_kept(server):
    c = http.client.HTTPConnection("127.0.0.1", server.port)
    c.request("GET", "/js/main.js", headers={"Host": "evil.example"})
    assert c.getresponse().status == 403
