from rest_framework import serializers
from .models import Organisations


class OrganisationSerializer(serializers.ModelSerializer):
    logo_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Organisations
        fields = ['id', 'name', 'website', 'logo', 'logo_url', 'language']
        extra_kwargs = {
            'logo': {'write_only': True, 'required': False}
        }
    
    def get_logo_url(self, obj):
        if obj.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.logo.url)
            return obj.logo.url
        return None
    
    def validate(self, data):
        # Only validate name uniqueness on create, not update
        if self.instance is None:  # Creating new
            if Organisations.objects.filter(name=data.get('name')).exists():
                raise serializers.ValidationError({"error": "Organisation Already Exist"})
        return data
    
    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        instance.save()
        return instance
