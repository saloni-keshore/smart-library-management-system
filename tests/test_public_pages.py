from html.parser import HTMLParser


class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs = set()

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.hrefs.update(value for name, value in attrs if name == "href")


def page_links(response):
    parser = LinkCollector()
    parser.feed(response.get_data(as_text=True))
    return parser.hrefs


def test_public_pages_render_without_authentication(client):
    for path, heading in (
        ("/home", "Make every library day run"),
        ("/privacy-policy", "Privacy Policy"),
        ("/terms-of-service", "Terms of Service"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert heading.encode() in response.data


def test_public_pages_link_to_each_other(client):
    home_links = page_links(client.get("/home"))
    assert "/privacy-policy" in home_links
    assert "/terms-of-service" in home_links

    for path in ("/privacy-policy", "/terms-of-service"):
        links = page_links(client.get(path))
        assert {"/home", "/privacy-policy", "/terms-of-service"} <= links


def test_login_route_remains_public_root_route(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"Username or Mobile Number" in response.data
    assert client.application.view_functions["auth.login"]
