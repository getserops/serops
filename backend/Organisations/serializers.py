import base64

from rest_framework import serializers
from Utils.images import ImageRejected, to_small_png
from .models import Organisations

LOGO_MAX_SIDE = 256


class OrganisationSerializer(serializers.ModelSerializer):
    # Write: an image file, or an empty value to remove the logo.
    # Read: ``logo_url``, a data URL usable directly as an <img> src
    # (an /images/ URL would need an authenticated media route).
    logo = serializers.ImageField(write_only=True, required=False, allow_null=True, allow_empty_file=False)
    logo_url = serializers.SerializerMethodField()

    class Meta:
        model = Organisations
        fields = ['id', 'name', 'website', 'logo', 'logo_url', 'language']

    def get_logo_url(self, obj):
        if obj.logo_png:
            return 'data:image/png;base64,' + base64.b64encode(bytes(obj.logo_png)).decode('ascii')
        return None

    def to_internal_value(self, data):
        # Multipart sends "remove" as an empty string, which ImageField
        # rejects; map it to None.
        if hasattr(data, 'get') and data.get('logo') == '':
            data = {key: data.get(key) for key in data}
            data['logo'] = None
        return super().to_internal_value(data)

    def validate_logo(self, value):
        if not value:
            return None
        try:
            return to_small_png(value, LOGO_MAX_SIDE)
        except ImageRejected as exc:
            raise serializers.ValidationError(str(exc))

    def validate(self, data):
        # Only validate name uniqueness on create, not update
        if self.instance is None:  # Creating new
            if Organisations.objects.filter(name=data.get('name')).exists():
                raise serializers.ValidationError({"error": "Organisation Already Exist"})
        if 'logo' in data:
            data['logo_png'] = data.pop('logo')
        return data

    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        instance.save()
        return instance
