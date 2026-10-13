from django.contrib import admin
from Users.models import User

class UserAdmin(admin.ModelAdmin):
    # Show user info but focus on the key fields
    list_display = ('email', 'first_name', 'last_name', 'role', 'organisation', 'status', 'is_active')
    
    # Group fields in the edit form
    fieldsets = (
        ('User Management', {
            'fields': ('role', 'organisation', 'status')
        }),
    )
    
    # Make these fields editable from list view
    list_editable = ('role', 'status')
    
    # Add filters
    list_filter = ('role', 'status', 'organisation', 'is_active')
    
    # Search functionality
    search_fields = ('email', 'first_name', 'last_name')

    def has_add_permission(self, request):
        return False  # Prevent adding new users

# Just register with your custom admin
admin.site.register(User, UserAdmin)
