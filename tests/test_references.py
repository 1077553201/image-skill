import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image

from product_studio.references.sources import (normalize_url, checked_url, public_addresses,
                                              PublicReferenceHTTP, extract_images, collect)


def png():
    output = io.BytesIO()
    Image.new('RGB', (96, 80), 'blue').save(output, format='PNG')
    return output.getvalue()


class ReferenceTests(unittest.TestCase):
    def test_amazon_normalization(self):
        self.assertEqual(normalize_url('https://www.amazon.com/name/dp/B0HGGJZ92H?tag=x')['url'],
                         'https://www.amazon.com/dp/B0HGGJZ92H')

    def test_ebay_id(self):
        self.assertEqual(normalize_url('https://www.ebay.co.uk/itm/item/123456789012?x=1')['product_id'], '123456789012')

    def test_unsafe_urls(self):
        for url in ['http://www.amazon.com/dp/B0HGGJZ92H', 'https://127.0.0.1/a',
                    'https://www.amazon.com.evil.test/a', 'https://user@www.amazon.com/a',
                    'https://www.amazon.com:8080/a', 'file:///C:/test', 'https://www.amazon.com\\@localhost/a']:
            with self.subTest(url=url), self.assertRaises(ValueError):
                checked_url(url)

    def test_bad_product_url(self):
        with self.assertRaises(ValueError):
            normalize_url('https://www.amazon.com/search?q=x')

    def test_private_dns_rejected(self):
        for address in ['127.0.0.1', '192.168.1.171', '169.254.169.254', '::1', '::ffff:127.0.0.1']:
            with self.subTest(address=address), patch.object(socket, 'getaddrinfo', return_value=[(None,None,None,None,(address,443))]), self.assertRaises(ValueError):
                public_addresses('www.amazon.com')

    def test_gallery_not_ads(self):
        html = "'colorImages': { 'initial': A.$.parseJSON('[{\"hiRes\":\"https://m.media-amazon.com/images/I/test.jpg\",\"variant\":\"MAIN\"}]') }"
        html += '<div class="ad"><img src="https://m.media-amazon.com/images/I/advert.jpg"></div>'
        images = extract_images(html, 'amazon')
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]['role'], 'main')

    def test_aplus_scoping(self):
        images = extract_images('<div id="aplus"><img src="https://m.media-amazon.com/images/I/a.jpg"></div><img src="https://m.media-amazon.com/images/I/out.jpg">', 'amazon')
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0]['role'], 'detail_or_aplus')

    def test_ebay_product_schema(self):
        images = extract_images('<script type="application/ld+json">{"@type":"Product","image":["https://i.ebayimg.com/images/a.jpg"]}</script>', 'ebay')
        self.assertEqual(len(images), 1)

    def test_captcha_no_bypass(self):
        with self.assertRaises(RuntimeError):
            extract_images('<form action="validateCaptcha">', 'amazon')

    def test_local_screenshot_hashes_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'screen.png').write_bytes(png())
            result = collect(root/'out', local=root/'screen.png', screenshot=True)
            self.assertEqual(result['assets'][0]['size_px'], [96,80])
            self.assertTrue(result['assets'][0]['internal_analysis_only'])
            self.assertTrue((root/'out/reference_contact_sheet.png').is_file())
            with self.assertRaises(ValueError):
                collect(root/'out', local=root/'screen.png')

    def test_zip_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root/'bad.zip', 'w') as z:
                z.writestr('../outside.png', png())
            with self.assertRaises(ValueError):
                collect(root/'out', local=root/'bad.zip')
            self.assertFalse((root/'outside.png').exists())

    def test_failed_collection_honest_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'html').write_text('<html>missing gallery</html>')
            with self.assertRaises(RuntimeError):
                collect(root/'out', url='https://www.amazon.com/dp/B0HGGJZ92H', saved_html=root/'html')
            manifest = json.loads((root/'out/catalog.json').read_text())
            self.assertEqual(manifest['status'], 'failed')
            self.assertEqual(manifest['assets'], [])

    def test_redirect_private_rejected_before_connect(self):
        from product_studio.references import sources
        response = unittest.mock.Mock(status=302)
        response.getheader.return_value = 'https://127.0.0.1/private'
        connection = unittest.mock.Mock()
        connection.getresponse.return_value = response
        with patch.object(sources, 'public_addresses', return_value=['8.8.8.8']), patch.object(sources, '_PinnedHTTPS', return_value=connection):
            with self.assertRaises(ValueError):
                PublicReferenceHTTP().get('https://www.amazon.com/dp/B0HGGJZ92H')
        connection.close.assert_called_once()
