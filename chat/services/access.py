class TaskAccess:
    PERMISSION = "chat.view_temporal_tasks"
    DENIED = "You don't have access to Temporal tasks."

    @classmethod
    def allowed(cls, user):
        return bool(user is not None and user.is_authenticated and user.has_perm(cls.PERMISSION))
