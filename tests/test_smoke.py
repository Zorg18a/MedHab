def test_index_loads_and_has_six_nav_links(page, server):
    page.goto(server.url)
    assert page.locator("nav a").count() == 6
