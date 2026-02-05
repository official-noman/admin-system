"""
forms.py

All application forms live here.

Conventions:
    - Every form has a docstring.
    - Every visible field has a placeholder — UX consistency.
    - Custom error_messages on every required / validated field
      so users never see Django's raw default messages.
    - Validation lives in clean_<field> methods (no logic in views).
    - Security:  password fields never expose plain-text values
      (render_value=True is intentionally avoided).
"""

import re

from django import forms

from .models import CompanyProfile, Device, User


# =============================================================================
# 1.  UserCreationFormCustom
# =============================================================================
class UserCreationFormCustom(forms.ModelForm):
    """Create a new User and hash the password before saving.

    Password must be at least 8 characters — enforced at the form level
    so the error message is user-friendly (not a DB-level crash).
    """

    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={
            "class":       "form-control",
            "placeholder": "Enter Password (min 8 characters)",
        }),
        error_messages={
            "required":  "Password is required.",
            "min_length": "Password must be at least 8 characters.",
        },
    )

    class Meta:
        model  = User
        fields = ["username", "email", "password"]
        widgets = {
            "username": forms.TextInput(attrs={
                "class":       "form-control",
                "placeholder": "Enter Username",
            }),
            "email": forms.EmailInput(attrs={
                "class":       "form-control",
                "placeholder": "Enter Email",
            }),
        }
        error_messages = {
            "username": {
                "required": "Username is required.",
                "unique":   "A user with this username already exists.",
            },
            "email": {
                "required": "Email is required.",
                "invalid":  "Enter a valid email address.",
            },
        }

    # ------------------------------------------------------------------
    # save — hash the password before persisting
    # ------------------------------------------------------------------
    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


# =============================================================================
# 2.  CompanyProfileForm
# =============================================================================
class CompanyProfileForm(forms.ModelForm):
    """Update a company's public profile.

    - company_name  / license_number  are mandatory.
    - website       auto-prepends https:// when the scheme is missing.
    - phone_number  is validated with a simple regex so junk input is
      rejected before it hits the database.
    """

    company_name = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "class":       "form-control",
            "placeholder": "Enter Company Name",
        }),
        error_messages={
            "required": "Company name is required.",
        },
    )

    license_number = forms.CharField(
        required=True,
        widget=forms.TextInput(attrs={
            "class":       "form-control",
            "placeholder": "Enter License Number",
        }),
        error_messages={
            "required": "License number is required.",
        },
    )

    class Meta:
        model  = CompanyProfile
        fields = [
            "company_name",
            "license_number",
            "company_email",
            "location",
            "website",
            "phone_number",
        ]
        widgets = {
            "company_email": forms.EmailInput(attrs={
                "class":       "form-control",
                "placeholder": "company@example.com",
            }),
            "location": forms.TextInput(attrs={
                "class":       "form-control",
                "placeholder": "City, Country",
            }),
            "website": forms.URLInput(attrs={
                "class":       "form-control",
                "placeholder": "example.com",
            }),
            "phone_number": forms.TextInput(attrs={
                "class":       "form-control",
                "placeholder": "+880 1234 567890",
            }),
        }
        error_messages = {
            "company_email": {
                "invalid": "Enter a valid email address.",
            },
            "website": {
                "invalid": "Enter a valid URL (e.g. example.com).",
            },
        }

    # ------------------------------------------------------------------
    # clean_website — auto-prepend https:// if missing
    # ------------------------------------------------------------------
    def clean_website(self):
        url = self.cleaned_data.get("website")
        if url and not url.startswith(("http://", "https://")):
            url = f"https://{url}"
        return url

    # ------------------------------------------------------------------
    # clean_phone_number — reject non-numeric junk
    #   Accepted formats:  +880 1234 567890 | 01234567890 | +8801234567890
    # ------------------------------------------------------------------
    def clean_phone_number(self):
        phone = self.cleaned_data.get("phone_number")
        if phone:
            # Strip spaces / dashes that users commonly type
            normalized = re.sub(r"[\s\-]", "", phone)

            if not re.match(r"^\+?\d{7,15}$", normalized):
                raise forms.ValidationError(
                    "Enter a valid phone number (e.g. +880 1234 567890)."
                )
            return normalized          # save the clean version
        return phone


# =============================================================================
# 3.  DeviceForm
# =============================================================================
class DeviceForm(forms.ModelForm):
    """Add or edit a Device record.

    - On *create*  the password field is required.
    - On *edit*    the password field is optional — left blank means
      "keep the current password" (handled in __init__ + clean_password).
    - render_value is intentionally kept False so existing passwords
      are never echoed back to the browser.
    """

    class Meta:
        model  = Device
        fields = ["operator", "sim_number", "password", "sim_pin"]
        widgets = {
            "operator": forms.Select(attrs={
                "class": "form-select",
            }),
            "sim_number": forms.TextInput(attrs={
                "class":       "form-control",
                "placeholder": "Enter SIM Number",
            }),
            "password": forms.PasswordInput(attrs={       # render_value defaults to False
                "class":       "form-control",
                "placeholder": "Enter Device Password",
            }),
            "sim_pin": forms.TextInput(attrs={
                "class":       "form-control",
                "placeholder": "Enter SIM PIN",
            }),
        }
        error_messages = {
            "operator":   {"required": "Please select an operator."},
            "sim_number": {"required": "SIM number is required."},
            "password":   {"required": "Device password is required."},
            "sim_pin":    {"required": "SIM PIN is required."},
        }

    # ------------------------------------------------------------------
    # __init__ — relax password requirement when editing an existing device
    # ------------------------------------------------------------------
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:                                # existing device
            self.fields["password"].required = False
            self.fields["password"].widget.attrs["placeholder"] = (
                "Leave blank to keep current password"
            )

    # ------------------------------------------------------------------
    # clean_sim_number — length guard so a bad value never reaches the DB
    # ------------------------------------------------------------------
    def clean_sim_number(self):
        value = self.cleaned_data.get("sim_number", "").strip()
        if len(value) > 20:
            raise forms.ValidationError("SIM number must not exceed 20 characters.")
        return value

    # ------------------------------------------------------------------
    # clean_sim_pin — length guard
    # ------------------------------------------------------------------
    def clean_sim_pin(self):
        value = self.cleaned_data.get("sim_pin", "").strip()
        if len(value) > 8:
            raise forms.ValidationError("SIM PIN must not exceed 8 characters.")
        return value

    # ------------------------------------------------------------------
    # clean_password — on edit, keep old password if field left blank
    # ------------------------------------------------------------------
    def clean_password(self):
        password = self.cleaned_data.get("password")

        if not password and self.instance.pk:
            # User left the field blank during edit → keep existing value
            return self.instance.password

        return password