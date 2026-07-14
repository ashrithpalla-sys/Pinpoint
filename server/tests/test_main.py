import httpx
import pytest

import MAIN


# ── Pure functions ────────────────────────────────────────────────────────────

class TestIsBlocked:
    def test_exact_match(self):
        assert MAIN.is_blocked("https://instagram.com/some/post") is True

    def test_subdomain_match(self):
        assert MAIN.is_blocked("https://www.instagram.com/some/post") is True
        assert MAIN.is_blocked("https://m.facebook.com/page") is True

    def test_unrelated_domain_not_blocked(self):
        assert MAIN.is_blocked("https://www.everlane.com/products/shirt") is False

    def test_substring_lookalike_not_blocked(self):
        # must not match just because "instagram.com" is a substring
        assert MAIN.is_blocked("https://notinstagram.com/product") is False

    def test_wikipedia_and_wikimedia_are_actually_blocked(self):
        # regression: host.lstrip("www.") used to strip a leading "w" character
        # from any host (not the literal "www." prefix), corrupting
        # "wikipedia.org" -> "ikipedia.org" so it silently failed to match
        assert MAIN.is_blocked("https://wikipedia.org/wiki/Shirt") is True
        assert MAIN.is_blocked("https://www.wikipedia.org/wiki/Shirt") is True
        assert MAIN.is_blocked("https://wikimedia.org/wiki/File:x.png") is True

    def test_case_insensitive(self):
        assert MAIN.is_blocked("https://WWW.INSTAGRAM.COM/post") is True

    def test_malformed_url_returns_false(self):
        assert MAIN.is_blocked("") is False
        assert MAIN.is_blocked("not a url at all") is False


class TestPriceMatchesRegion:
    def test_match_found(self):
        assert MAIN.price_matches_region("$49.99", ["$", "USD"]) is True

    def test_no_match(self):
        assert MAIN.price_matches_region("€49.99", ["$", "USD"]) is False

    def test_empty_string(self):
        assert MAIN.price_matches_region("", ["$", "USD"]) is False
        assert MAIN.price_matches_region(None, ["$", "USD"]) is False

    def test_compound_symbol_does_not_false_positive_for_bare_symbol(self):
        # regression: bare "$" used to match as a substring of "A$"/"C$"/"S$",
        # so a US region would wrongly accept an Australian/Canadian/
        # Singaporean price as if it were USD
        assert MAIN.price_matches_region("A$50.00", ["$", "USD"]) is False
        assert MAIN.price_matches_region("C$50.00", ["$", "USD"]) is False
        assert MAIN.price_matches_region("S$50.00", ["$", "USD"]) is False

    def test_compound_symbol_still_matches_when_it_is_the_allowed_symbol(self):
        assert MAIN.price_matches_region("A$50.00", ["A$", "AUD"]) is True

    def test_multiple_allowed_symbols(self):
        assert MAIN.price_matches_region("Rs 500", ["₹", "INR", "Rs"]) is True


class TestParsePriceValue:
    def test_none_and_empty(self):
        assert MAIN.parse_price_value(None) is None
        assert MAIN.parse_price_value("") is None

    def test_comma_formatted(self):
        assert MAIN.parse_price_value("$1,234.56") == 1234.56

    def test_zero_returns_none(self):
        assert MAIN.parse_price_value("$0") is None
        assert MAIN.parse_price_value("$0.00") is None

    def test_no_digits_returns_none(self):
        assert MAIN.parse_price_value("Free") is None

    def test_malformed_returns_none(self):
        assert MAIN.parse_price_value("$.") is None

    def test_simple_value(self):
        assert MAIN.parse_price_value("USD 45") == 45.0


class TestParseDataUrl:
    def test_valid_png(self):
        mime, data = MAIN.parse_data_url("data:image/png;base64,aGVsbG8=")
        assert mime == "image/png"
        assert data == b"hello"

    def test_valid_jpeg(self):
        mime, data = MAIN.parse_data_url("data:image/jpeg;base64,aGVsbG8=")
        assert mime == "image/jpeg"
        assert data == b"hello"

    def test_missing_mime_prefix_falls_back(self):
        mime, data = MAIN.parse_data_url("nonstandard,aGVsbG8=")
        assert mime == "image/png"
        assert data == b"hello"


class TestExtractPriceFromHtml:
    def test_json_ld_matching_currency(self):
        html = """
        <script type="application/ld+json">
        {"offers": {"price": "49.99", "priceCurrency": "USD"}}
        </script>
        """
        assert MAIN.extract_price_from_html(html, ["$", "USD"]) == "USD 49.99"

    def test_json_ld_wrong_currency_falls_through_to_regex(self):
        html = """
        <script type="application/ld+json">
        {"offers": {"price": "49.99", "priceCurrency": "EUR"}}
        </script>
        <div>On sale now for $39.99 today only!</div>
        """
        assert MAIN.extract_price_from_html(html, ["$", "USD"]) == "$39.99"

    def test_regression_first_match_out_of_range_second_match_used(self):
        # the exact bug we fixed: the old loop always re-checked the FIRST
        # regex match no matter what, so an implausible first match (here,
        # an absurd $ figure) would block real later matches from ever
        # being considered
        html = "Insurance surcharge $999999 — actual price today: $59.99"
        assert MAIN.extract_price_from_html(html, ["$", "USD"]) == "$59.99"

    def test_malformed_json_ld_does_not_crash(self):
        html = """
        <script type="application/ld+json">{not valid json}</script>
        <div>Price: $19.99</div>
        """
        assert MAIN.extract_price_from_html(html, ["$", "USD"]) == "$19.99"

    def test_no_price_anywhere_returns_none(self):
        html = "<div>No pricing information available.</div>"
        assert MAIN.extract_price_from_html(html, ["$", "USD"]) is None


class TestClassifySerpApiError:
    def test_quota_exhausted_by_status(self):
        msg = MAIN.classify_serpapi_error(429, '{"error": "Your account has run out of searches."}')
        assert "quota" in msg.lower()

    def test_quota_exhausted_by_body_text_even_with_unknown_status(self):
        msg = MAIN.classify_serpapi_error(None, "Your account has run out of searches.")
        assert "quota" in msg.lower()

    def test_invalid_api_key(self):
        msg = MAIN.classify_serpapi_error(401, '{"error": "Invalid API key."}')
        assert "credentials" in msg.lower()

    def test_transient_server_error(self):
        msg = MAIN.classify_serpapi_error(503, "")
        assert "try again" in msg.lower()

    def test_unknown_failure_gets_generic_message(self):
        msg = MAIN.classify_serpapi_error(500, "")
        assert msg  # non-empty, doesn't crash


class TestClassifyCloudinaryError:
    def test_permission_error(self):
        msg = MAIN.classify_cloudinary_error("Request forbidden due to missing permissions")
        assert "permission" in msg.lower()

    def test_invalid_credentials(self):
        msg = MAIN.classify_cloudinary_error("Invalid API credentials")
        assert "credentials" in msg.lower()

    def test_unknown_failure_gets_generic_message(self):
        msg = MAIN.classify_cloudinary_error("Failed to ping image")
        assert msg  # non-empty, doesn't crash


# ── Async functions (mocked I/O) ──────────────────────────────────────────────

class TestScrapePrice:
    async def test_200_with_extractable_price(self, httpx_mock):
        httpx_mock.add_response(url="https://shop.example.com/item", text="<div>$29.99</div>")
        async with httpx.AsyncClient() as client:
            price, reachable = await MAIN.scrape_price("https://shop.example.com/item", client, ["$", "USD"])
        assert price == "$29.99"
        assert reachable is True

    async def test_200_with_no_price(self, httpx_mock):
        httpx_mock.add_response(url="https://shop.example.com/item", text="<div>no price here</div>")
        async with httpx.AsyncClient() as client:
            price, reachable = await MAIN.scrape_price("https://shop.example.com/item", client, ["$", "USD"])
        assert price is None
        assert reachable is True

    async def test_non_200_status_is_unreachable(self, httpx_mock):
        httpx_mock.add_response(url="https://shop.example.com/gone", status_code=404, text="Not Found")
        async with httpx.AsyncClient() as client:
            price, reachable = await MAIN.scrape_price("https://shop.example.com/gone", client, ["$", "USD"])
        assert price is None
        assert reachable is False

    async def test_connection_error_is_unreachable(self, httpx_mock):
        httpx_mock.add_exception(httpx.ConnectError("connection refused"), url="https://shop.example.com/down")
        async with httpx.AsyncClient() as client:
            price, reachable = await MAIN.scrape_price("https://shop.example.com/down", client, ["$", "USD"])
        assert price is None
        assert reachable is False


class TestEnrichPrices:
    async def test_existing_price_is_left_untouched_no_fetch(self, httpx_mock):
        products = [{"price": "$10.00", "link": "https://shop.example.com/a", "source": "A"}]
        result = await MAIN.enrich_prices(products, ["$", "USD"])
        assert result[0]["price"] == "$10.00"
        assert len(httpx_mock.get_requests()) == 0

    async def test_unreachable_link_gets_flagged(self, httpx_mock):
        httpx_mock.add_response(url="https://shop.example.com/dead", status_code=404, text="Not Found")
        products = [{"price": None, "link": "https://shop.example.com/dead", "source": "Dead Shop"}]
        result = await MAIN.enrich_prices(products, ["$", "USD"])
        assert result[0].get("_unreachable") is True

    async def test_reachable_with_price_sets_price_no_flag(self, httpx_mock):
        httpx_mock.add_response(url="https://shop.example.com/live", text="<div>$15.00</div>")
        products = [{"price": None, "link": "https://shop.example.com/live", "source": "Live Shop"}]
        result = await MAIN.enrich_prices(products, ["$", "USD"])
        assert result[0]["price"] == "$15.00"
        assert "_unreachable" not in result[0]
