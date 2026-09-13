from django.contrib import admin

from tracker import models


@admin.register(models.Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "school", "graduation_date")


@admin.register(models.Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "user", "status", "match_category")
    list_filter = ("status", "match_category")


admin.site.register(models.ProfileTrack)
admin.site.register(models.ApplicationMaterial)
admin.site.register(models.Task)
admin.site.register(models.Contact)
