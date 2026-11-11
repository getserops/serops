from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Data.audit import log_action
from Middlewares.rbac import Requires

from .licensing import store
from .licensing.verify import LicenseError, verify
from .models import InstalledLicense


class LicenseView(APIView):
    """
    The Enterprise license key of this install.

    GET shows the installed license (never the key). PUT installs a key: a
    JSON body ``{"license": "<key>"}`` or a ``file`` upload. DELETE removes
    it. Installing replaces any previous key. Install-wide, so it needs
    ``license.manage`` (platform staff, or the admin of a single-organisation
    install).
    """

    permission_classes = [
        IsAuthenticated,
        Requires(GET='license.manage', PUT='license.manage', DELETE='license.manage'),
    ]

    def get(self, request):
        return Response(store.summary())

    def put(self, request):
        upload = request.FILES.get('file')
        if upload is not None:
            try:
                text = upload.read(64 * 1024 + 1).decode('utf-8')
            except UnicodeDecodeError:
                return Response({'error': 'The file is not a license key'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            text = request.data.get('license')
        try:
            lic = verify(text)
        except LicenseError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if lic.is_expired():
            return Response(
                {'error': f'This license expired on {lic.expires.isoformat()}'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        InstalledLicense.objects.all().delete()
        InstalledLicense.objects.create(raw=text.strip(), installed_by=request.user)
        store.clear_cache()
        log_action(request, 'SETTINGS_CHANGE', {
            'setting': 'enterprise_license', 'change': 'installed', 'license_id': lic.id,
            'licensee': lic.licensee, 'features': sorted(lic.features), 'expires': lic.expires.isoformat(),
        })
        return Response(store.summary())

    def delete(self, request):
        deleted, _ = InstalledLicense.objects.all().delete()
        store.clear_cache()
        if deleted:
            log_action(request, 'SETTINGS_CHANGE', {'setting': 'enterprise_license', 'change': 'removed'})
        return Response(status=status.HTTP_204_NO_CONTENT)
