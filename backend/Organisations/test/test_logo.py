import base64
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from rest_framework import status
from rest_framework.test import APITestCase

from Organisations.models import Organisations
from Users.models import User


def image_upload(size=(64, 64), fmt='JPEG', name='logo.jpg'):
    buf = io.BytesIO()
    Image.new('RGB', size, (15, 118, 110)).save(buf, format=fmt)
    return SimpleUploadedFile(name, buf.getvalue(), content_type=f'image/{fmt.lower()}')


def decode(logo_url):
    prefix = 'data:image/png;base64,'
    assert logo_url.startswith(prefix), logo_url[:40]
    return Image.open(io.BytesIO(base64.b64decode(logo_url[len(prefix):])))


class OrganisationLogoTest(APITestCase):
    """The logo is stored in the database and returned as a data URL, so it
    shows on installs with several backend pods and DEBUG off."""

    def setUp(self):
        self.org = Organisations.objects.create(name='Logo Org')
        self.admin = User.objects.create_user(
            username='logoadmin', email='logoadmin@example.com', password='x',
            organisation=self.org, role='admin')
        self.client.force_authenticate(user=self.admin)
        self.url = reverse('organisation-info')

    def test_no_logo_by_default(self):
        self.assertIsNone(self.client.get(self.url).data['logo_url'])

    def test_upload_returns_png_data_url(self):
        response = self.client.put(self.url, {'logo': image_upload()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(decode(response.data['logo_url']).format, 'PNG')
        self.assertEqual(self.client.get(self.url).data['logo_url'], response.data['logo_url'])

    def test_large_image_is_shrunk(self):
        response = self.client.put(self.url, {'logo': image_upload(size=(1200, 600))}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(decode(response.data['logo_url']).size, (256, 128))

    def test_non_image_rejected(self):
        upload = SimpleUploadedFile('logo.png', b'<svg onload=alert(1)>', content_type='image/png')
        response = self.client.put(self.url, {'logo': upload}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.org.refresh_from_db()
        self.assertIsNone(self.org.logo_png)

    def test_empty_value_removes_logo(self):
        self.client.put(self.url, {'logo': image_upload()}, format='multipart')
        response = self.client.put(self.url, {'logo': ''}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNone(response.data['logo_url'])

    def test_other_fields_keep_logo(self):
        self.client.put(self.url, {'logo': image_upload()}, format='multipart')
        response = self.client.put(self.url, {'website': 'https://example.com'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNotNone(response.data['logo_url'])

    def test_viewer_cannot_upload(self):
        viewer = User.objects.create_user(
            username='logoviewer', email='logoviewer@example.com', password='x',
            organisation=self.org, role='viewer')
        self.client.force_authenticate(user=viewer)
        response = self.client.put(self.url, {'logo': image_upload()}, format='multipart')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
