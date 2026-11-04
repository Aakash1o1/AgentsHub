from django.utils.html import format_html, format_html_join
from django.urls import reverse


class AdminHtml:
    @staticmethod
    def colored_badge(text, color):
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>', color, text
        )

    @staticmethod
    def chip_list(items):
        css_class = (
            "font-medium px-2 py-1 rounded-default text-xs whitespace-nowrap bg-base-100 "
            "text-base-700 dark:bg-base-800 dark:text-base-200"
        )
        chips = format_html_join("", '<span class="{}">{}</span>', ((css_class, item) for item in items))
        return format_html('<div class="flex flex-wrap gap-1.5">{}</div>', chips) if chips else "-"

    @staticmethod
    def js_action_button(label, css_class, **data):
        attrs = format_html_join(
            "", ' data-{}="{}"', ((k.replace("_", "-"), v) for k, v in data.items())
        )
        return format_html(
            '<button type="button" class="{}"{}>{}</button>', css_class, attrs, label
        )

    @staticmethod
    def link_button(url, label, icon=None, download=False):
        css_class = (
            "font-medium inline-flex items-center gap-1 rounded-default justify-center "
            "whitespace-nowrap cursor-pointer px-2.5 py-1.5 border border-base-200 bg-white "
            "shadow-xs text-important dark:border-base-700 dark:bg-transparent "
            "hover:bg-base-100/80 dark:hover:bg-base-800/80"
        )
        icon_html = format_html('<span class="material-symbols-outlined text-base">{}</span> ', icon) if icon else ""
        return format_html(
            '<a href="{}"{} class="{}">{}{}</a>',
            url, " download" if download else "", css_class, icon_html, label,
        )

    @staticmethod
    def change_link(obj, label=None):
        url = reverse(
            f"admin:{obj._meta.app_label}_{obj._meta.model_name}_change",
            args=[obj.pk],
        )
        return format_html('<a href="{}">{}</a>', url, label or f"{obj._meta.model_name}{obj.pk}")
