from tracker.models import Profile


def ensure_profile(user) -> Profile:
    profile, _ = Profile.objects.get_or_create(
        user=user,
        defaults={"full_name": user.get_full_name() or user.username},
    )
    return profile
